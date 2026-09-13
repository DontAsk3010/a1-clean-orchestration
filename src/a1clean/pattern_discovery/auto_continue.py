from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from ..google_drive import build_drive_api
from .contracts import DiscoveryPlan, LANE_ID, PatternDiscoveryContractError
from .drive_store import Lane2DriveStore
from .runner import (
    CHECKPOINT_SCHEMA,
    EVIDENCE_MANIFEST_SCHEMA,
    RUN_RESULT_SCHEMA,
    _load_plan,
    _safe_token,
    run_source_discovery,
)
from .source_reader import GovernedSourceReader, SemanticManifestRow

AUTO_CONTINUATION_SCHEMA = "A1_LANE2_GOVERNED_AUTO_CONTINUATION_V1"
AUTO_CONTINUATION_STATUS_RUNNING = "RUNNING"
AUTO_CONTINUATION_STATUS_HOLD = "HOLD"
AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE = "CORPUS_COMPLETE"
PASS_RESULT_STATUS = "PASS_COMPLETE_GOVERNED_SCOPE_DISCOVERY_EVIDENCE"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TradingDateScope:
    trading_date: str
    manifest_index_first: int
    manifest_index_last: int
    packet_count: int
    source_row_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date,
            "manifest_index_first": self.manifest_index_first,
            "manifest_index_last": self.manifest_index_last,
            "packet_count": self.packet_count,
            "source_row_count": self.source_row_count,
        }


def build_trading_date_scopes(rows: Iterable[SemanticManifestRow]) -> tuple[TradingDateScope, ...]:
    scopes: list[TradingDateScope] = []
    seen_dates: set[str] = set()
    active_date: str | None = None
    active_first = 0
    active_last = 0
    active_packets = 0
    active_rows = 0
    previous_date: date | None = None

    def flush() -> None:
        nonlocal active_date, active_first, active_last, active_packets, active_rows
        if active_date is None:
            return
        scopes.append(
            TradingDateScope(
                trading_date=active_date,
                manifest_index_first=active_first,
                manifest_index_last=active_last,
                packet_count=active_packets,
                source_row_count=active_rows,
            )
        )

    for ordinal, row in enumerate(rows):
        try:
            parsed_date = date.fromisoformat(row.trading_date)
        except ValueError as exc:
            raise PatternDiscoveryContractError(
                f"AUTO_CONTINUATION_MANIFEST_DATE_INVALID:{row.trading_date}"
            ) from exc
        manifest_index = int(getattr(row, "manifest_index", ordinal))
        if active_date is None:
            active_date = row.trading_date
            active_first = manifest_index
            active_last = manifest_index
            active_packets = 1
            active_rows = int(row.data_row_count)
            seen_dates.add(active_date)
            previous_date = parsed_date
            continue
        if row.trading_date == active_date:
            active_last = manifest_index
            active_packets += 1
            active_rows += int(row.data_row_count)
            continue
        if row.trading_date in seen_dates:
            raise PatternDiscoveryContractError(
                f"AUTO_CONTINUATION_MANIFEST_DATE_NOT_CONTIGUOUS:{row.trading_date}"
            )
        if previous_date is not None and parsed_date <= previous_date:
            raise PatternDiscoveryContractError(
                f"AUTO_CONTINUATION_MANIFEST_DATE_NOT_STRICTLY_CHRONOLOGICAL:{active_date}:{row.trading_date}"
            )
        flush()
        active_date = row.trading_date
        active_first = manifest_index
        active_last = manifest_index
        active_packets = 1
        active_rows = int(row.data_row_count)
        seen_dates.add(active_date)
        previous_date = parsed_date
    flush()
    if not scopes:
        raise PatternDiscoveryContractError("AUTO_CONTINUATION_MANIFEST_EMPTY")
    return tuple(scopes)


def next_trading_date_scope(
    scopes: tuple[TradingDateScope, ...],
    *,
    after_date: str,
) -> TradingDateScope | None:
    matches = [idx for idx, scope in enumerate(scopes) if scope.trading_date == after_date]
    if len(matches) != 1:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_ANCHOR_DATE_CARDINALITY:{after_date}:{len(matches)}"
        )
    next_index = matches[0] + 1
    return scopes[next_index] if next_index < len(scopes) else None


def _validate_source_and_plan(
    *,
    reader: GovernedSourceReader,
    plan: DiscoveryPlan,
    expected_source_drive_id: str,
    expected_source_sha256: str,
    expected_plan_fingerprint: str,
) -> None:
    if reader.identity.source_drive_id != expected_source_drive_id:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_SOURCE_DRIVE_ID_MISMATCH:{reader.identity.source_drive_id}"
        )
    if reader.identity.source_sha256 != expected_source_sha256:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_SOURCE_SHA256_MISMATCH:{reader.identity.source_sha256}"
        )
    if plan.sha256 != expected_plan_fingerprint:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_PLAN_FINGERPRINT_MISMATCH:{plan.sha256}"
        )


def validate_complete_pass_checkpoint(
    checkpoint: dict[str, Any],
    *,
    reader: GovernedSourceReader,
    plan: DiscoveryPlan,
    scope: TradingDateScope,
) -> None:
    expected_scope = {"scope_type": "EXACT_TRADING_DATE", "trading_date": scope.trading_date}
    checks = {
        "schema": checkpoint.get("schema") == CHECKPOINT_SCHEMA,
        "lane_id": checkpoint.get("lane_id") == LANE_ID,
        "status": checkpoint.get("status") == "PASS",
        "source_identity": checkpoint.get("source_identity") == reader.identity.as_dict(),
        "plan_id": checkpoint.get("plan_id") == plan.plan_id,
        "plan_fingerprint": checkpoint.get("plan_fingerprint") == plan.sha256,
        "scope": checkpoint.get("scope") == expected_scope,
        "total_manifest_packets": int(checkpoint.get("total_manifest_packets") or -1) == scope.packet_count,
        "completed_manifest_packets": int(checkpoint.get("completed_manifest_packets") or -1) == scope.packet_count,
        "selected_source_rows": int(checkpoint.get("selected_source_rows") or -1) == scope.source_row_count,
        "completed_source_rows": int(checkpoint.get("completed_source_rows") or -1) == scope.source_row_count,
        "hold": checkpoint.get("hold") is None,
        "next_exact_resume_point": checkpoint.get("next_exact_resume_point") is None,
        "evidence_manifest": isinstance(checkpoint.get("evidence_manifest"), dict),
        "run_result": isinstance(checkpoint.get("run_result"), dict),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_PASS_GATE_FAILED:{scope.trading_date}:{','.join(failed)}"
        )


def _json_from_item(store: Lane2DriveStore, item: dict[str, Any], *, role: str) -> dict[str, Any]:
    try:
        obj = json.loads(store.read_bytes(item).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_JSON_INVALID") from exc
    if not isinstance(obj, dict):
        raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_NOT_OBJECT")
    return obj


def _verify_upload_reference(
    *,
    items_by_id: dict[str, dict[str, Any]],
    upload_ref: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    file_id = str(upload_ref.get("id") or "")
    item = items_by_id.get(file_id)
    if item is None:
        raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_MISSING:{file_id}")
    if item.get("name") != upload_ref.get("name"):
        raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_NAME_MISMATCH:{file_id}")
    if int(item.get("size") or -1) != int(upload_ref.get("size") or -2):
        raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_SIZE_MISMATCH:{file_id}")
    if item.get("md5Checksum") != upload_ref.get("md5"):
        raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_MD5_MISMATCH:{file_id}")
    return item


def find_verified_pass_checkpoint(
    *,
    store: Lane2DriveStore,
    reader: GovernedSourceReader,
    plan: DiscoveryPlan,
    scope: TradingDateScope,
) -> dict[str, Any] | None:
    prefix = (
        f"{reader.stem}__{_safe_token(plan.plan_id)}__DATE_{_safe_token(scope.trading_date)}__"
    )
    control_items = [
        item
        for item in store._folder_items(store.control_folder_id)
        if str(item.get("name") or "").startswith(prefix)
        and str(item.get("name") or "").endswith("__LANE2_CHECKPOINT.json")
    ]
    if not control_items:
        return None

    evidence_by_id = {
        str(item["id"]): item for item in store._folder_items(store.evidence_folder_id)
    }
    audit_by_id = {
        str(item["id"]): item for item in store._folder_items(store.audit_folder_id)
    }
    valid: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for item in control_items:
        checkpoint = _json_from_item(store, item, role="CHECKPOINT")
        if checkpoint.get("status") != "PASS":
            continue
        try:
            validate_complete_pass_checkpoint(
                checkpoint,
                reader=reader,
                plan=plan,
                scope=scope,
            )
            evidence_item = _verify_upload_reference(
                items_by_id=evidence_by_id,
                upload_ref=checkpoint["evidence_manifest"],
                role="EVIDENCE_MANIFEST",
            )
            audit_item = _verify_upload_reference(
                items_by_id=audit_by_id,
                upload_ref=checkpoint["run_result"],
                role="RUN_RESULT",
            )
            evidence_obj = _json_from_item(store, evidence_item, role="EVIDENCE_MANIFEST")
            result_obj = _json_from_item(store, audit_item, role="RUN_RESULT")
            if evidence_obj.get("schema") != EVIDENCE_MANIFEST_SCHEMA:
                raise PatternDiscoveryContractError("AUTO_CONTINUATION_EVIDENCE_MANIFEST_SCHEMA_MISMATCH")
            if result_obj.get("schema") != RUN_RESULT_SCHEMA:
                raise PatternDiscoveryContractError("AUTO_CONTINUATION_RUN_RESULT_SCHEMA_MISMATCH")
            if result_obj.get("pass") is not True or result_obj.get("status") != PASS_RESULT_STATUS:
                raise PatternDiscoveryContractError("AUTO_CONTINUATION_RUN_RESULT_NOT_PASS")
            for obj, role in ((evidence_obj, "EVIDENCE_MANIFEST"), (result_obj, "RUN_RESULT")):
                if obj.get("run_key") != checkpoint.get("run_key"):
                    raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_RUN_KEY_MISMATCH")
                if obj.get("source_identity") != reader.identity.as_dict():
                    raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_SOURCE_IDENTITY_MISMATCH")
                if obj.get("plan_fingerprint") != plan.sha256:
                    raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_PLAN_MISMATCH")
                if obj.get("scope") != {"scope_type": "EXACT_TRADING_DATE", "trading_date": scope.trading_date}:
                    raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_SCOPE_MISMATCH")
                if int(obj.get("packet_count") or -1) != scope.packet_count:
                    raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_PACKET_COUNT_MISMATCH")
                if int(obj.get("source_row_count") or -1) != scope.source_row_count:
                    raise PatternDiscoveryContractError(f"AUTO_CONTINUATION_{role}_ROW_COUNT_MISMATCH")
            valid.append((str(item.get("modifiedTime") or ""), checkpoint, item))
        except PatternDiscoveryContractError:
            continue
    if not valid:
        return None
    valid.sort(key=lambda entry: entry[0])
    _, checkpoint, item = valid[-1]
    return {
        "checkpoint": checkpoint,
        "checkpoint_file": {
            "id": str(item["id"]),
            "name": str(item["name"]),
            "modifiedTime": item.get("modifiedTime"),
        },
    }


def _state_name(reader: GovernedSourceReader, plan: DiscoveryPlan) -> str:
    return (
        f"{reader.stem}__{_safe_token(plan.plan_id)}__"
        "GOVERNED_AUTO_CONTINUATION_STATE.json"
    )


def run_governed_auto_continuation(
    *,
    source_name: str,
    expected_source_drive_id: str,
    expected_source_sha256: str,
    plan_path: Path,
    expected_plan_fingerprint: str,
    packets_per_shard: int,
    software_revision: str,
    anchor_passed_date: str,
) -> dict[str, Any]:
    if packets_per_shard <= 0:
        raise PatternDiscoveryContractError("AUTO_CONTINUATION_PACKETS_PER_SHARD_MUST_BE_POSITIVE")
    if not software_revision or software_revision == "LOCAL_UNVERSIONED":
        raise PatternDiscoveryContractError("AUTO_CONTINUATION_SOFTWARE_REVISION_REQUIRED")

    reader = GovernedSourceReader(build_drive_api(read_write=False), source_name=source_name)
    plan = _load_plan(plan_path)
    _validate_source_and_plan(
        reader=reader,
        plan=plan,
        expected_source_drive_id=expected_source_drive_id,
        expected_source_sha256=expected_source_sha256,
        expected_plan_fingerprint=expected_plan_fingerprint,
    )
    scopes = build_trading_date_scopes(reader.semantic_manifest_rows)
    scope_by_date = {scope.trading_date: scope for scope in scopes}
    anchor_scope = scope_by_date.get(anchor_passed_date)
    if anchor_scope is None:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_ANCHOR_DATE_NOT_IN_GOVERNED_MANIFEST:{anchor_passed_date}"
        )

    store = Lane2DriveStore(build_drive_api(read_write=True))
    anchor_proof = find_verified_pass_checkpoint(
        store=store,
        reader=reader,
        plan=plan,
        scope=anchor_scope,
    )
    if anchor_proof is None:
        raise PatternDiscoveryContractError(
            f"AUTO_CONTINUATION_ANCHOR_NOT_VERIFIED_PASS:{anchor_passed_date}"
        )

    state_name = _state_name(reader, plan)
    next_scope = next_trading_date_scope(scopes, after_date=anchor_passed_date)
    state: dict[str, Any] = {
        "schema": AUTO_CONTINUATION_SCHEMA,
        "lane_id": LANE_ID,
        "status": AUTO_CONTINUATION_STATUS_RUNNING if next_scope else AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE,
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "software_revision": software_revision,
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "packets_per_shard": packets_per_shard,
        "transition_policy": "FINAL_VERIFIED_PASS_ONLY_THEN_NEXT_CHRONOLOGICAL_MANIFEST_DATE",
        "date_source": "GOVERNED_SEMANTIC_MANIFEST_NOT_CALENDAR_PLUS_ONE",
        "time_based_schedule_used": False,
        "main_branch_mutation_used": False,
        "anchor_passed_date": anchor_passed_date,
        "anchor_pass_proof": anchor_proof["checkpoint_file"],
        "last_completed_date": anchor_passed_date,
        "current_date": next_scope.trading_date if next_scope else None,
        "next_date": next_scope.trading_date if next_scope else None,
        "completed_dates_this_chain": [],
        "hold": None,
    }
    store.upsert_json(folder_id=store.control_folder_id, name=state_name, obj=state)

    if next_scope is None:
        return {
            "schema": AUTO_CONTINUATION_SCHEMA,
            "lane_id": LANE_ID,
            "pass": True,
            "status": AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE,
            "last_completed_date": anchor_passed_date,
            "next_date": None,
            "completed_dates_this_chain": [],
        }

    start_idx = next(idx for idx, scope in enumerate(scopes) if scope.trading_date == next_scope.trading_date)
    try:
        for scope in scopes[start_idx:]:
            state["status"] = AUTO_CONTINUATION_STATUS_RUNNING
            state["current_date"] = scope.trading_date
            state["next_date"] = scope.trading_date
            state["updated_at_utc"] = _utc_now()
            state["hold"] = None
            store.upsert_json(folder_id=store.control_folder_id, name=state_name, obj=state)

            proof = find_verified_pass_checkpoint(
                store=store,
                reader=reader,
                plan=plan,
                scope=scope,
            )
            reused_existing_pass = proof is not None
            if proof is None:
                report = run_source_discovery(
                    source_name=source_name,
                    plan_path=plan_path,
                    packets_per_shard=packets_per_shard,
                    software_revision=software_revision,
                    trading_date=scope.trading_date,
                    ticker=None,
                )
                if report.get("pass") is not True or report.get("status") not in {
                    PASS_RESULT_STATUS,
                    "NOOP_ALREADY_COMPLETE",
                }:
                    raise PatternDiscoveryContractError(
                        f"AUTO_CONTINUATION_DATE_RUNTIME_NOT_PASS:{scope.trading_date}:{report.get('status')}"
                    )
                proof = find_verified_pass_checkpoint(
                    store=store,
                    reader=reader,
                    plan=plan,
                    scope=scope,
                )
                if proof is None:
                    raise PatternDiscoveryContractError(
                        f"AUTO_CONTINUATION_POST_RUN_PASS_READBACK_FAILED:{scope.trading_date}"
                    )

            state["completed_dates_this_chain"].append(
                {
                    "trading_date": scope.trading_date,
                    "packet_count": scope.packet_count,
                    "source_row_count": scope.source_row_count,
                    "reused_existing_verified_pass": reused_existing_pass,
                    "checkpoint_file": proof["checkpoint_file"],
                    "completed_at_utc": _utc_now(),
                }
            )
            state["last_completed_date"] = scope.trading_date
            following = next_trading_date_scope(scopes, after_date=scope.trading_date)
            state["current_date"] = following.trading_date if following else None
            state["next_date"] = following.trading_date if following else None
            state["status"] = (
                AUTO_CONTINUATION_STATUS_RUNNING
                if following is not None
                else AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE
            )
            state["updated_at_utc"] = _utc_now()
            store.upsert_json(folder_id=store.control_folder_id, name=state_name, obj=state)
    except Exception as exc:
        state["status"] = AUTO_CONTINUATION_STATUS_HOLD
        state["updated_at_utc"] = _utc_now()
        state["hold"] = {
            "trading_date": state.get("current_date"),
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "resume_rule": "RESUME_SAME_DATE_FROM_PERSISTED_LANE2_CHECKPOINT_DO_NOT_ADVANCE",
        }
        store.upsert_json(folder_id=store.control_folder_id, name=state_name, obj=state)
        raise

    return {
        "schema": AUTO_CONTINUATION_SCHEMA,
        "lane_id": LANE_ID,
        "pass": True,
        "status": state["status"],
        "last_completed_date": state["last_completed_date"],
        "next_date": state["next_date"],
        "completed_dates_this_chain": state["completed_dates_this_chain"],
    }
