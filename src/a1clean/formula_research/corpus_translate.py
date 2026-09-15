from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from typing import Any, Mapping

from googleapiclient.http import MediaIoBaseUpload

from ..google_drive import build_drive_api
from ..source_parity import _download_bytes, _list_children
from ..pattern_discovery.resilience import call_with_retry
from .lane2_translate import (
    EXPECTED_LANE2_PLAN_FINGERPRINT,
    EXPECTED_LANE2_PLAN_ID,
    FormulaTranslationContractError,
    translate_lane2_packet_result,
)


CHECKPOINT_NAME = "A1_CURRENT_CLEAN_FORMULA_TRANSLATION_STATE.json"
AUDIT_NAME = "A1_CURRENT_CLEAN_FORMULA_TRANSLATION_AUDIT.json"
CHECKPOINT_SCHEMA = "A1_CURRENT_CLEAN_FORMULA_TRANSLATION_STATE_V1"
INPUT_MANIFEST_SCHEMA = "A1_ALGORITHMIC_PATTERN_DISCOVERY_EVIDENCE_MANIFEST_V1"
INPUT_LINE_SCHEMA = "A1_ALGORITHMIC_PATTERN_DISCOVERY_EVIDENCE_LINE_V1"
OUTPUT_LINE_SCHEMA = "A1_CURRENT_CLEAN_FORMULA_TRANSLATION_LINE_V1"
OUTPUT_MANIFEST_SCHEMA = "A1_CURRENT_CLEAN_FORMULA_TRANSLATION_MANIFEST_V1"
TRANSLATION_CONTRACT_ID = "CURRENT_CLEAN_LANE2_STRUCTURAL_TRANSLATION_V1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class _FolderStore:
    def __init__(self, api, folder_id: str):
        self.api = api
        self.folder_id = folder_id

    def _items(self) -> list[dict[str, Any]]:
        return call_with_retry(
            lambda: _list_children(
                self.api,
                self.folder_id,
                fields="id,name,mimeType,size,md5Checksum,modifiedTime",
            ),
            operation=f"formula.list_children:{self.folder_id}",
        )

    def get_optional(self, name: str) -> dict[str, Any] | None:
        matches = [row for row in self._items() if row.get("name") == name]
        if not matches:
            return None
        if len(matches) != 1:
            raise FormulaTranslationContractError(f"FORMULA_FILE_CARDINALITY:{name}:{len(matches)}")
        return matches[0]

    def read_bytes(self, item: Mapping[str, Any]) -> bytes:
        file_id = str(item["id"])
        return call_with_retry(
            lambda: _download_bytes(self.api, file_id),
            operation=f"formula.download:{file_id}",
        )

    def read_json_optional(self, name: str) -> dict[str, Any] | None:
        item = self.get_optional(name)
        if item is None:
            return None
        try:
            obj = json.loads(self.read_bytes(item).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FormulaTranslationContractError(f"FORMULA_JSON_INVALID:{name}") from exc
        if not isinstance(obj, dict):
            raise FormulaTranslationContractError(f"FORMULA_JSON_NOT_OBJECT:{name}")
        return obj

    def upsert_bytes(self, *, name: str, data: bytes, mime_type: str) -> dict[str, Any]:
        def _once() -> dict[str, Any]:
            existing = self.get_optional(name)
            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
            if existing is None:
                req = self.api.files().create(
                    body={"name": name, "parents": [self.folder_id]},
                    media_body=media,
                    fields="id,name,size,md5Checksum,parents,mimeType",
                    supportsAllDrives=True,
                )
            else:
                req = self.api.files().update(
                    fileId=str(existing["id"]),
                    media_body=media,
                    fields="id,name,size,md5Checksum,parents,mimeType",
                    supportsAllDrives=True,
                )
            return req.execute()

        result = call_with_retry(_once, operation=f"formula.upsert:{self.folder_id}:{name}")
        readback = call_with_retry(
            lambda: _download_bytes(self.api, str(result["id"])),
            operation=f"formula.readback:{result['id']}",
        )
        if readback != data:
            raise FormulaTranslationContractError(f"FORMULA_UPLOAD_READBACK_MISMATCH:{name}")
        return {
            "id": str(result["id"]),
            "name": name,
            "size": len(data),
            "sha256": _sha256(data),
            "md5": result.get("md5Checksum"),
            "parents": result.get("parents"),
        }

    def upsert_json(self, *, name: str, obj: Any) -> dict[str, Any]:
        return self.upsert_bytes(name=name, data=_canonical_json_bytes(obj), mime_type="application/json")


def _validate_false_assertions(assertions: Mapping[str, Any], *, where: str) -> None:
    keys = (
        "ai_event_journey_objects_consumed",
        "ai_semantic_labels_consumed",
        "formula_stage_opened",
        "outcomes_consumed",
        "sampling_used",
        "synthetic_rows_created",
        "trading_signal_created",
    )
    contaminated = [key for key in keys if bool(assertions.get(key))]
    if contaminated:
        raise FormulaTranslationContractError(f"INPUT_STAGE1_CONTAMINATION:{where}:{contaminated}")


def _load_input_manifests(reader_api, evidence_folder_id: str) -> list[dict[str, Any]]:
    items = call_with_retry(
        lambda: _list_children(
            reader_api,
            evidence_folder_id,
            fields="id,name,mimeType,size,md5Checksum,modifiedTime",
        ),
        operation=f"formula.list_input_evidence:{evidence_folder_id}",
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "")
        if not name.endswith("__EVIDENCE_MANIFEST.json"):
            continue
        raw = call_with_retry(
            lambda item=item: _download_bytes(reader_api, str(item["id"])),
            operation=f"formula.read_manifest:{item['id']}",
        )
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_JSON_INVALID:{name}") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != INPUT_MANIFEST_SCHEMA:
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_SCHEMA_INVALID:{name}")
        if manifest.get("plan_id") != EXPECTED_LANE2_PLAN_ID:
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_PLAN_ID_MISMATCH:{name}")
        if manifest.get("plan_fingerprint") != EXPECTED_LANE2_PLAN_FINGERPRINT:
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_PLAN_FP_MISMATCH:{name}")
        assertions = manifest.get("independence_assertions")
        if not isinstance(assertions, Mapping):
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_ASSERTIONS_MISSING:{name}")
        _validate_false_assertions(assertions, where=name)
        scope = manifest.get("scope") or {}
        if scope.get("scope_type") != "EXACT_TRADING_DATE" or not scope.get("trading_date"):
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_NOT_EXACT_DATE:{name}")
        rows.append(
            {
                "item": item,
                "raw": raw,
                "sha256": _sha256(raw),
                "manifest": manifest,
                "trading_date": str(scope["trading_date"]),
                "source_name": str((manifest.get("source_identity") or {}).get("source_name") or ""),
            }
        )
    rows.sort(key=lambda row: (row["trading_date"], row["source_name"], str(row["item"]["name"])))
    return rows


def _output_shard_name(input_name: str) -> str:
    if "__EVIDENCE_" not in input_name or not input_name.endswith(".jsonl"):
        raise FormulaTranslationContractError(f"INPUT_SHARD_NAME_INVALID:{input_name}")
    return input_name.replace("__EVIDENCE_", "__FORMULA_TRANSLATED_", 1)


def _output_manifest_name(input_name: str) -> str:
    if not input_name.endswith("__EVIDENCE_MANIFEST.json"):
        raise FormulaTranslationContractError(f"INPUT_MANIFEST_NAME_INVALID:{input_name}")
    return input_name.replace("__EVIDENCE_MANIFEST.json", "__FORMULA_TRANSLATION_MANIFEST.json")


def _translate_manifest(
    *,
    reader_api,
    output_store: _FolderStore,
    manifest_row: Mapping[str, Any],
    software_revision: str,
) -> dict[str, Any]:
    item = manifest_row["item"]
    manifest = manifest_row["manifest"]
    input_manifest_name = str(item["name"])
    output_shards: list[dict[str, Any]] = []
    packet_count = 0

    for shard in manifest.get("evidence_shards", []) or []:
        shard_id = str(shard.get("id") or "")
        shard_name = str(shard.get("name") or "")
        expected_sha = str(shard.get("sha256") or "")
        if not shard_id or not shard_name or not expected_sha:
            raise FormulaTranslationContractError(f"INPUT_SHARD_IDENTITY_INCOMPLETE:{input_manifest_name}")
        raw = call_with_retry(
            lambda shard_id=shard_id: _download_bytes(reader_api, shard_id),
            operation=f"formula.read_input_shard:{shard_id}",
        )
        actual_sha = _sha256(raw)
        if actual_sha != expected_sha:
            raise FormulaTranslationContractError(
                f"INPUT_SHARD_SHA256_MISMATCH:{shard_name}:EXPECTED={expected_sha}:ACTUAL={actual_sha}"
            )

        out = io.StringIO()
        shard_packets = 0
        for line_number, raw_line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not raw_line.strip():
                continue
            try:
                envelope = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise FormulaTranslationContractError(f"INPUT_EVIDENCE_LINE_JSON_INVALID:{shard_name}:{line_number}") from exc
            if envelope.get("schema") != INPUT_LINE_SCHEMA:
                raise FormulaTranslationContractError(f"INPUT_EVIDENCE_LINE_SCHEMA_INVALID:{shard_name}:{line_number}")
            if envelope.get("run_key") != manifest.get("run_key"):
                raise FormulaTranslationContractError(f"INPUT_EVIDENCE_RUN_KEY_MISMATCH:{shard_name}:{line_number}")
            translated = translate_lane2_packet_result(envelope.get("result") or {})
            output_line = {
                "schema": OUTPUT_LINE_SCHEMA,
                "translation_contract_id": TRANSLATION_CONTRACT_ID,
                "software_revision": software_revision,
                "input_evidence": {
                    "manifest_file_id": str(item["id"]),
                    "manifest_name": input_manifest_name,
                    "manifest_sha256": manifest_row["sha256"],
                    "shard_file_id": shard_id,
                    "shard_name": shard_name,
                    "shard_sha256": expected_sha,
                    "line_number": line_number,
                    "run_key": envelope.get("run_key"),
                    "scope": envelope.get("scope"),
                    "manifest_ref": envelope.get("manifest_ref"),
                },
                "translation": translated,
            }
            out.write(json.dumps(output_line, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
            out.write("\n")
            shard_packets += 1

        if shard_packets != int(shard.get("packet_count") or -1):
            raise FormulaTranslationContractError(
                f"INPUT_SHARD_PACKET_COUNT_MISMATCH:{shard_name}:EXPECTED={shard.get('packet_count')}:ACTUAL={shard_packets}"
            )
        encoded = out.getvalue().encode("utf-8")
        uploaded = output_store.upsert_bytes(
            name=_output_shard_name(shard_name),
            data=encoded,
            mime_type="application/x-ndjson",
        )
        output_shards.append(
            {
                **uploaded,
                "input_shard_file_id": shard_id,
                "input_shard_name": shard_name,
                "input_shard_sha256": expected_sha,
                "packet_count": shard_packets,
                "shard_ordinal": shard.get("shard_ordinal"),
            }
        )
        packet_count += shard_packets

    expected_packets = int(manifest.get("packet_count") or -1)
    if packet_count != expected_packets:
        raise FormulaTranslationContractError(
            f"INPUT_MANIFEST_PACKET_COUNT_MISMATCH:{input_manifest_name}:EXPECTED={expected_packets}:ACTUAL={packet_count}"
        )

    output_manifest = {
        "schema": OUTPUT_MANIFEST_SCHEMA,
        "translation_contract_id": TRANSLATION_CONTRACT_ID,
        "created_at_utc": _utc_now(),
        "software_revision": software_revision,
        "input_evidence_manifest": {
            "id": str(item["id"]),
            "name": input_manifest_name,
            "sha256": manifest_row["sha256"],
            "run_key": manifest.get("run_key"),
        },
        "source_identity": manifest.get("source_identity"),
        "scope": manifest.get("scope"),
        "lane2_plan_id": manifest.get("plan_id"),
        "lane2_plan_fingerprint": manifest.get("plan_fingerprint"),
        "selection_fingerprint": manifest.get("selection_fingerprint"),
        "input_packet_count": expected_packets,
        "translated_packet_count": packet_count,
        "input_source_row_count": manifest.get("source_row_count"),
        "output_shard_count": len(output_shards),
        "output_shards": output_shards,
        "semantic_reconciliation_required_before_final_formula": True,
        "outcomes_consumed": False,
        "signal_created": False,
        "threshold_created": False,
        "ranking_created": False,
        "status": "PASS",
    }
    uploaded_manifest = output_store.upsert_json(
        name=_output_manifest_name(input_manifest_name),
        obj=output_manifest,
    )
    return {
        "trading_date": manifest_row["trading_date"],
        "source_name": manifest_row["source_name"],
        "input_manifest_id": str(item["id"]),
        "input_manifest_name": input_manifest_name,
        "input_manifest_sha256": manifest_row["sha256"],
        "output_manifest": uploaded_manifest,
        "packet_count": packet_count,
        "output_shard_count": len(output_shards),
    }


def run_lane2_corpus_translation(
    *,
    evidence_folder_id: str,
    output_folder_id: str,
    control_folder_id: str,
    audit_folder_id: str,
    software_revision: str,
    max_manifests: int = 0,
) -> dict[str, Any]:
    if not all([evidence_folder_id, output_folder_id, control_folder_id, audit_folder_id, software_revision]):
        raise FormulaTranslationContractError("FORMULA_TRANSLATION_REQUIRED_ARGUMENT_MISSING")
    if max_manifests < 0:
        raise FormulaTranslationContractError("MAX_MANIFESTS_MUST_BE_ZERO_OR_POSITIVE")

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    output_store = _FolderStore(writer_api, output_folder_id)
    control_store = _FolderStore(writer_api, control_folder_id)
    audit_store = _FolderStore(writer_api, audit_folder_id)
    manifests = _load_input_manifests(reader_api, evidence_folder_id)
    if not manifests:
        raise FormulaTranslationContractError("NO_FINAL_LANE2_EVIDENCE_MANIFESTS_FOUND")

    checkpoint = control_store.read_json_optional(CHECKPOINT_NAME)
    if checkpoint is None:
        checkpoint = {
            "schema": CHECKPOINT_SCHEMA,
            "translation_contract_id": TRANSLATION_CONTRACT_ID,
            "created_at_utc": _utc_now(),
            "updated_at_utc": _utc_now(),
            "evidence_folder_id": evidence_folder_id,
            "output_folder_id": output_folder_id,
            "control_folder_id": control_folder_id,
            "audit_folder_id": audit_folder_id,
            "lane2_plan_id": EXPECTED_LANE2_PLAN_ID,
            "lane2_plan_fingerprint": EXPECTED_LANE2_PLAN_FINGERPRINT,
            "status": "IN_PROGRESS",
            "hold": None,
            "completed_manifests": [],
            "completed_packet_count": 0,
            "last_completed": None,
            "next_exact_manifest": None,
        }
    identity = {
        "schema": checkpoint.get("schema"),
        "translation_contract_id": checkpoint.get("translation_contract_id"),
        "evidence_folder_id": checkpoint.get("evidence_folder_id"),
        "output_folder_id": checkpoint.get("output_folder_id"),
        "control_folder_id": checkpoint.get("control_folder_id"),
        "audit_folder_id": checkpoint.get("audit_folder_id"),
        "lane2_plan_id": checkpoint.get("lane2_plan_id"),
        "lane2_plan_fingerprint": checkpoint.get("lane2_plan_fingerprint"),
    }
    expected_identity = {
        "schema": CHECKPOINT_SCHEMA,
        "translation_contract_id": TRANSLATION_CONTRACT_ID,
        "evidence_folder_id": evidence_folder_id,
        "output_folder_id": output_folder_id,
        "control_folder_id": control_folder_id,
        "audit_folder_id": audit_folder_id,
        "lane2_plan_id": EXPECTED_LANE2_PLAN_ID,
        "lane2_plan_fingerprint": EXPECTED_LANE2_PLAN_FINGERPRINT,
    }
    if identity != expected_identity:
        raise FormulaTranslationContractError("FORMULA_TRANSLATION_CHECKPOINT_IDENTITY_MISMATCH")

    completed = {
        (str(row.get("input_manifest_id")), str(row.get("input_manifest_sha256")))
        for row in checkpoint.get("completed_manifests", []) or []
    }
    pending = [
        row for row in manifests if (str(row["item"]["id"]), str(row["sha256"])) not in completed
    ]
    total_available = len(manifests)
    bounded = pending[:max_manifests] if max_manifests else pending

    try:
        for row in bounded:
            checkpoint["status"] = "IN_PROGRESS"
            checkpoint["hold"] = None
            checkpoint["next_exact_manifest"] = {
                "id": str(row["item"]["id"]),
                "name": str(row["item"]["name"]),
                "sha256": row["sha256"],
                "trading_date": row["trading_date"],
            }
            checkpoint["updated_at_utc"] = _utc_now()
            control_store.upsert_json(name=CHECKPOINT_NAME, obj=checkpoint)

            record = _translate_manifest(
                reader_api=reader_api,
                output_store=output_store,
                manifest_row=row,
                software_revision=software_revision,
            )
            checkpoint["completed_manifests"].append(record)
            checkpoint["completed_packet_count"] = int(checkpoint.get("completed_packet_count") or 0) + int(record["packet_count"])
            checkpoint["last_completed"] = record
            checkpoint["next_exact_manifest"] = None
            checkpoint["updated_at_utc"] = _utc_now()
            control_store.upsert_json(name=CHECKPOINT_NAME, obj=checkpoint)
    except Exception as exc:
        checkpoint["status"] = "HOLD"
        checkpoint["hold"] = {"error_type": type(exc).__name__, "reason": str(exc)}
        checkpoint["updated_at_utc"] = _utc_now()
        control_store.upsert_json(name=CHECKPOINT_NAME, obj=checkpoint)
        raise

    complete_keys = {
        (str(row.get("input_manifest_id")), str(row.get("input_manifest_sha256")))
        for row in checkpoint.get("completed_manifests", []) or []
    }
    remaining = [
        row for row in manifests if (str(row["item"]["id"]), str(row["sha256"])) not in complete_keys
    ]
    is_complete = not remaining
    checkpoint["status"] = (
        "TRANSLATION_CORPUS_COMPLETE_FOR_AVAILABLE_LANE2_EVIDENCE" if is_complete else "IN_PROGRESS_BOUNDED"
    )
    checkpoint["hold"] = None
    checkpoint["updated_at_utc"] = _utc_now()
    checkpoint["available_manifest_count"] = total_available
    checkpoint["completed_manifest_count"] = len(checkpoint.get("completed_manifests", []))
    checkpoint["remaining_manifest_count"] = len(remaining)
    checkpoint["next_exact_manifest"] = (
        {
            "id": str(remaining[0]["item"]["id"]),
            "name": str(remaining[0]["item"]["name"]),
            "sha256": remaining[0]["sha256"],
            "trading_date": remaining[0]["trading_date"],
        }
        if remaining
        else None
    )
    checkpoint_file = control_store.upsert_json(name=CHECKPOINT_NAME, obj=checkpoint)

    audit = {
        "schema": "A1_CURRENT_CLEAN_FORMULA_TRANSLATION_AUDIT_V1",
        "translation_contract_id": TRANSLATION_CONTRACT_ID,
        "created_at_utc": _utc_now(),
        "software_revision": software_revision,
        "pass": True,
        "status": checkpoint["status"],
        "available_manifest_count": total_available,
        "completed_manifest_count": checkpoint["completed_manifest_count"],
        "remaining_manifest_count": len(remaining),
        "completed_packet_count": checkpoint["completed_packet_count"],
        "checkpoint_file": checkpoint_file,
        "semantic_reconciliation_required_before_final_formula": True,
        "final_formula_created": False,
        "trading_signal_created": False,
    }
    audit_file = audit_store.upsert_json(name=AUDIT_NAME, obj=audit)
    return {**audit, "audit_file": audit_file}
