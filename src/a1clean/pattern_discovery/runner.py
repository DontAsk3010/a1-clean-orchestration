from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
from typing import Any

from ..google_drive import build_drive_api
from .contracts import DiscoveryPlan, LANE_ID, PatternDiscoveryContractError, fingerprint
from .drive_store import Lane2DriveStore, sha256_bytes
from .engine import INDEPENDENCE_ASSERTIONS, run_discovery_plan
from .source_reader import GovernedSourceReader

RUNNER_SCHEMA = "A1_ALGORITHMIC_PATTERN_DISCOVERY_SOURCE_RUN_V1"
CHECKPOINT_SCHEMA = "A1_ALGORITHMIC_PATTERN_DISCOVERY_CHECKPOINT_V1"
EVIDENCE_MANIFEST_SCHEMA = "A1_ALGORITHMIC_PATTERN_DISCOVERY_EVIDENCE_MANIFEST_V1"
RUN_RESULT_SCHEMA = "A1_ALGORITHMIC_PATTERN_DISCOVERY_RUN_RESULT_V1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_token(text: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    token = token.strip("._-")
    if not token:
        raise PatternDiscoveryContractError("SAFE_TOKEN_EMPTY")
    return token


def _load_plan(path: Path) -> DiscoveryPlan:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PatternDiscoveryContractError(f"DISCOVERY_PLAN_READ_FAILED:{path}") from exc
    if not isinstance(obj, dict):
        raise PatternDiscoveryContractError("DISCOVERY_PLAN_NOT_OBJECT")
    return DiscoveryPlan.from_dict(obj)


def _next_ref(reader: GovernedSourceReader, next_index: int) -> dict[str, Any] | None:
    if next_index >= len(reader.semantic_manifest_rows):
        return None
    return reader.semantic_manifest_rows[next_index].as_dict()


def _checkpoint_name(reader: GovernedSourceReader, plan: DiscoveryPlan) -> str:
    return f"{reader.stem}__{_safe_token(plan.plan_id)}__LANE2_CHECKPOINT_CURRENT.json"


def _run_key(reader: GovernedSourceReader, plan: DiscoveryPlan) -> str:
    return fingerprint(
        {
            "runner_schema": RUNNER_SCHEMA,
            "lane_id": LANE_ID,
            "source": reader.identity.as_dict(),
            "plan": plan.as_dict(),
        }
    )[:24]


def _evidence_shard_name(reader: GovernedSourceReader, plan: DiscoveryPlan, run_key: str, shard_ordinal: int) -> str:
    return (
        f"{reader.stem}__{_safe_token(plan.plan_id)}__{run_key}__"
        f"EVIDENCE_{shard_ordinal:05d}.jsonl"
    )


def _evidence_manifest_name(reader: GovernedSourceReader, plan: DiscoveryPlan, run_key: str) -> str:
    return f"{reader.stem}__{_safe_token(plan.plan_id)}__{run_key}__EVIDENCE_MANIFEST.json"


def _run_result_name(reader: GovernedSourceReader, plan: DiscoveryPlan, run_key: str) -> str:
    return f"{reader.stem}__{_safe_token(plan.plan_id)}__{run_key}__RUN_RESULT.json"


def _validate_checkpoint(
    checkpoint: dict[str, Any],
    *,
    reader: GovernedSourceReader,
    plan: DiscoveryPlan,
    run_key: str,
    packets_per_shard: int,
    software_revision: str,
) -> None:
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "lane_id": LANE_ID,
        "run_key": run_key,
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "packets_per_shard": packets_per_shard,
        "software_revision": software_revision,
    }
    actual = {key: checkpoint.get(key) for key in expected}
    if actual != expected:
        raise PatternDiscoveryContractError(
            f"CHECKPOINT_IDENTITY_MISMATCH:EXPECTED_FP={fingerprint(expected)}:ACTUAL_FP={fingerprint(actual)}"
        )


def _verify_completed_shards(store: Lane2DriveStore, checkpoint: dict[str, Any]) -> None:
    folder_items = {item["name"]: item for item in store._folder_items(store.evidence_folder_id)}
    for shard in checkpoint.get("evidence_shards", []):
        item = folder_items.get(shard["name"])
        if item is None:
            raise PatternDiscoveryContractError(f"COMPLETED_EVIDENCE_SHARD_MISSING:{shard['name']}")
        actual_size = int(item["size"]) if item.get("size") is not None else None
        if actual_size != shard.get("size") or item.get("md5Checksum") != shard.get("md5"):
            raise PatternDiscoveryContractError(
                f"COMPLETED_EVIDENCE_SHARD_METADATA_MISMATCH:{shard['name']}"
            )


def _base_checkpoint(
    *,
    reader: GovernedSourceReader,
    plan: DiscoveryPlan,
    run_key: str,
    packets_per_shard: int,
    software_revision: str,
) -> dict[str, Any]:
    return {
        "schema": CHECKPOINT_SCHEMA,
        "lane_id": LANE_ID,
        "run_key": run_key,
        "status": "IN_PROGRESS",
        "created_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "plan": plan.as_dict(),
        "packets_per_shard": packets_per_shard,
        "software_revision": software_revision,
        "independence_assertions": dict(INDEPENDENCE_ASSERTIONS),
        "total_manifest_packets": len(reader.semantic_manifest_rows),
        "completed_manifest_packets": 0,
        "completed_source_rows": 0,
        "evidence_shards": [],
        "last_completed": None,
        "next_exact_resume_point": _next_ref(reader, 0),
        "hold": None,
    }


def _persist_hold(
    store: Lane2DriveStore,
    checkpoint_name: str,
    checkpoint: dict[str, Any],
    *,
    manifest_index: int,
    error: Exception,
    reader: GovernedSourceReader,
) -> None:
    checkpoint["status"] = "HOLD"
    checkpoint["updated_at_utc"] = _utc_now()
    checkpoint["hold"] = {
        "manifest_index": manifest_index,
        "error_type": type(error).__name__,
        "reason": str(error),
        "next_exact_resume_point": _next_ref(reader, manifest_index),
    }
    checkpoint["next_exact_resume_point"] = _next_ref(reader, manifest_index)
    store.upsert_json(folder_id=store.control_folder_id, name=checkpoint_name, obj=checkpoint)


def run_source_discovery(
    *,
    source_name: str,
    plan_path: Path,
    packets_per_shard: int,
    software_revision: str,
) -> dict[str, Any]:
    if packets_per_shard <= 0:
        raise PatternDiscoveryContractError("PACKETS_PER_SHARD_MUST_BE_POSITIVE")
    if not software_revision or software_revision == "LOCAL_UNVERSIONED":
        raise PatternDiscoveryContractError("SOFTWARE_REVISION_REQUIRED")

    plan = _load_plan(plan_path)
    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    reader = GovernedSourceReader(reader_api, source_name=source_name)
    store = Lane2DriveStore(writer_api)
    run_key = _run_key(reader, plan)
    checkpoint_name = _checkpoint_name(reader, plan)
    checkpoint = store.read_json_optional(store.control_folder_id, checkpoint_name)
    if checkpoint is None:
        checkpoint = _base_checkpoint(
            reader=reader,
            plan=plan,
            run_key=run_key,
            packets_per_shard=packets_per_shard,
            software_revision=software_revision,
        )
        store.upsert_json(folder_id=store.control_folder_id, name=checkpoint_name, obj=checkpoint)
    else:
        _validate_checkpoint(
            checkpoint,
            reader=reader,
            plan=plan,
            run_key=run_key,
            packets_per_shard=packets_per_shard,
            software_revision=software_revision,
        )
        _verify_completed_shards(store, checkpoint)
        if checkpoint.get("status") == "PASS":
            return {
                "schema": RUN_RESULT_SCHEMA,
                "lane_id": LANE_ID,
                "pass": True,
                "status": "NOOP_ALREADY_COMPLETE",
                "run_key": run_key,
                "source_identity": reader.identity.as_dict(),
                "plan_id": plan.plan_id,
                "plan_fingerprint": plan.sha256,
                "completed_manifest_packets": checkpoint.get("completed_manifest_packets"),
                "total_manifest_packets": checkpoint.get("total_manifest_packets"),
                "next_exact_resume_point": None,
            }
        if checkpoint.get("status") not in {"IN_PROGRESS", "HOLD"}:
            raise PatternDiscoveryContractError(f"CHECKPOINT_STATUS_UNSUPPORTED:{checkpoint.get('status')}")
        checkpoint["status"] = "IN_PROGRESS"
        checkpoint["hold"] = None
        checkpoint["updated_at_utc"] = _utc_now()
        store.upsert_json(folder_id=store.control_folder_id, name=checkpoint_name, obj=checkpoint)

    start_index = int(checkpoint.get("completed_manifest_packets") or 0)
    total = len(reader.semantic_manifest_rows)
    shard_ordinal = len(checkpoint.get("evidence_shards", [])) + 1

    while start_index < total:
        end_index = min(start_index + packets_per_shard, total)
        buffer = io.StringIO()
        shard_source_rows = 0
        try:
            for manifest_index in range(start_index, end_index):
                ref = reader.semantic_manifest_rows[manifest_index]
                packet = reader.load_packet(manifest_index)
                result = run_discovery_plan(packet, plan)
                envelope = {
                    "schema": "A1_ALGORITHMIC_PATTERN_DISCOVERY_EVIDENCE_LINE_V1",
                    "lane_id": LANE_ID,
                    "run_key": run_key,
                    "manifest_ref": ref.as_dict(),
                    "result": result,
                }
                buffer.write(json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
                buffer.write("\n")
                shard_source_rows += packet.row_count
        except Exception as exc:
            failing_index = manifest_index if "manifest_index" in locals() else start_index
            _persist_hold(
                store,
                checkpoint_name,
                checkpoint,
                manifest_index=failing_index,
                error=exc,
                reader=reader,
            )
            raise

        shard_bytes = buffer.getvalue().encode("utf-8")
        shard_name = _evidence_shard_name(reader, plan, run_key, shard_ordinal)
        uploaded = store.upsert_bytes(
            folder_id=store.evidence_folder_id,
            name=shard_name,
            data=shard_bytes,
            mime_type="application/x-ndjson",
        )
        shard_record = {
            **uploaded,
            "shard_ordinal": shard_ordinal,
            "manifest_index_first": start_index,
            "manifest_index_last": end_index - 1,
            "packet_count": end_index - start_index,
            "source_row_count": shard_source_rows,
        }
        checkpoint["evidence_shards"].append(shard_record)
        checkpoint["completed_manifest_packets"] = end_index
        checkpoint["completed_source_rows"] = int(checkpoint.get("completed_source_rows") or 0) + shard_source_rows
        checkpoint["last_completed"] = reader.semantic_manifest_rows[end_index - 1].as_dict()
        checkpoint["next_exact_resume_point"] = _next_ref(reader, end_index)
        checkpoint["updated_at_utc"] = _utc_now()
        checkpoint["status"] = "IN_PROGRESS" if end_index < total else "RECONCILING"
        store.upsert_json(folder_id=store.control_folder_id, name=checkpoint_name, obj=checkpoint)
        start_index = end_index
        shard_ordinal += 1

    _verify_completed_shards(store, checkpoint)
    packet_count = int(checkpoint["completed_manifest_packets"])
    source_rows = int(checkpoint["completed_source_rows"])
    expected_rows = int(reader.identity.source_data_rows)
    if packet_count != total:
        raise PatternDiscoveryContractError(f"FINAL_PACKET_COUNT_MISMATCH:{packet_count}:{total}")
    if source_rows != expected_rows:
        raise PatternDiscoveryContractError(f"FINAL_SOURCE_ROW_COUNT_MISMATCH:{source_rows}:{expected_rows}")

    evidence_manifest = {
        "schema": EVIDENCE_MANIFEST_SCHEMA,
        "lane_id": LANE_ID,
        "run_key": run_key,
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "plan": plan.as_dict(),
        "software_revision": software_revision,
        "storage_partition_policy": {
            "packets_per_shard": packets_per_shard,
            "analytical_semantics_affected": False,
            "shards_are_permanent_evidence_partitions_not_temporary_sampling_chunks": True,
        },
        "independence_assertions": dict(INDEPENDENCE_ASSERTIONS),
        "packet_count": packet_count,
        "source_row_count": source_rows,
        "evidence_shard_count": len(checkpoint["evidence_shards"]),
        "evidence_shards": checkpoint["evidence_shards"],
        "reconciliation": {
            "exact_semantic_manifest_packet_coverage": True,
            "exact_source_row_accounting": True,
            "no_sampling": True,
            "no_synthetic_rows": True,
            "ai_semantic_labels_consumed": False,
            "outcomes_consumed": False,
        },
        "created_at_utc": _utc_now(),
    }
    evidence_manifest_upload = store.upsert_json(
        folder_id=store.evidence_folder_id,
        name=_evidence_manifest_name(reader, plan, run_key),
        obj=evidence_manifest,
    )
    result = {
        "schema": RUN_RESULT_SCHEMA,
        "lane_id": LANE_ID,
        "pass": True,
        "status": "PASS_COMPLETE_SOURCE_DISCOVERY_EVIDENCE",
        "run_key": run_key,
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "software_revision": software_revision,
        "packet_count": packet_count,
        "source_row_count": source_rows,
        "evidence_shard_count": len(checkpoint["evidence_shards"]),
        "evidence_manifest": evidence_manifest_upload,
        "independence_assertions": dict(INDEPENDENCE_ASSERTIONS),
        "next_exact_resume_point": None,
        "finished_at_utc": _utc_now(),
    }
    result_upload = store.upsert_json(
        folder_id=store.audit_folder_id,
        name=_run_result_name(reader, plan, run_key),
        obj=result,
    )
    checkpoint["status"] = "PASS"
    checkpoint["updated_at_utc"] = _utc_now()
    checkpoint["next_exact_resume_point"] = None
    checkpoint["hold"] = None
    checkpoint["evidence_manifest"] = evidence_manifest_upload
    checkpoint["run_result"] = result_upload
    store.upsert_json(folder_id=store.control_folder_id, name=checkpoint_name, obj=checkpoint)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run governed independent algorithmic pattern discovery for one source.")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--packets-per-shard", required=True, type=int)
    parser.add_argument("--software-revision", default=os.environ.get("GITHUB_SHA", "LOCAL_UNVERSIONED"))
    args = parser.parse_args(argv)
    result = run_source_discovery(
        source_name=args.source_name,
        plan_path=args.plan,
        packets_per_shard=args.packets_per_shard,
        software_revision=args.software_revision,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
