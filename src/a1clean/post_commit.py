from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .canonical_promotion import _staging_control_map
from .config import (
    BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
    BEHAVIOR_CONTROL_FOLDER_NAME,
    CANONICAL_CURRENT_FOLDER_NAME,
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    PARITY_STAGING_FOLDER_NAME,
)
from .delta_artifacts import (
    DATA_PLANE_CONTROL_FILE_NAMES,
    SEMANTIC_CONTROL_FILE_NAMES,
    baseline_controls,
    upload_json_payload,
)
from .delta_machine import run_governed_delta_machine
from .delta_state import persistent_state_fingerprint
from .google_drive import build_drive_api
from .source_parity import (
    FOLDER_MIME,
    _assert_folder,
    _baseline_runtime_children,
    _create_folder,
    _download_json,
    _exact_named,
    _list_children,
)

POST_COMMIT_SCHEMA = "A1_POST_COMMIT_GOVERNED_READBACK_V2_MATERIAL_DELTA"
POST_COMMIT_NAME = "A1_CLEAN_POST_COMMIT_GOVERNED_READBACK"
POST_COMMIT_RESULT = "POST_COMMIT_READBACK_RESULT.json"

# These fields describe the execution that produced a control artifact, not a
# change in canonical market/source/semantic state. They are deliberately
# excluded only from the *promotion decision*. The raw artifacts retain every
# field and canonical promotion still uses exact hash/size reconciliation.
_VOLATILE_CONTROL_KEYS = frozenset(
    {
        "created_at_utc",
        "updated_at_utc",
        "started_at_utc",
        "finished_at_utc",
        "refresh_id",
        "delta_refresh_id",
        "runtime_input_fingerprint",
    }
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _snapshot_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _material_projection(value: Any) -> Any:
    """Remove run-volatile metadata while preserving governed state semantics.

    This prevents a source-watch/activation cycle from writing canonical controls
    merely because a new refresh timestamp/id was generated. Source identity,
    classification, semantic checkpoint provenance/watermarks, work items, holds,
    source hashes and every other governed field remain part of the comparison.
    """
    if isinstance(value, dict):
        return {
            key: _material_projection(item)
            for key, item in sorted(value.items())
            if key not in _VOLATILE_CONTROL_KEYS
        }
    if isinstance(value, list):
        return [_material_projection(item) for item in value]
    return value


def _material_fingerprint(payload: Any) -> str:
    return _snapshot_fingerprint(_material_projection(payload))


def _row(item: dict, *, target: str) -> dict:
    return {
        "target": target,
        "id": item.get("id"),
        "name": item.get("name"),
        "size": int(item["size"]) if item.get("size") is not None else None,
        "md5": item.get("md5Checksum"),
    }


def canonical_control_snapshot(reader_api) -> dict:
    folders = _baseline_runtime_children(reader_api)
    manifest_items = _list_children(reader_api, str(folders["00_MANIFESTS"]["id"]))
    semantic_items = _list_children(reader_api, BEHAVIOR_CONTROL_FOLDER_DRIVE_ID)

    data_rows = [
        _row(_exact_named(manifest_items, name), target="DATA_PLANE")
        for name in DATA_PLANE_CONTROL_FILE_NAMES
    ]
    semantic_rows = [
        _row(_exact_named(semantic_items, name), target="SEMANTIC_CONTROL")
        for name in SEMANTIC_CONTROL_FILE_NAMES
    ]
    payload = {
        "data_plane": sorted(data_rows, key=lambda row: row["name"]),
        "semantic_control": sorted(semantic_rows, key=lambda row: row["name"]),
    }
    return {**payload, "fingerprint": _snapshot_fingerprint(payload)}


def _control_diff_row(
    *,
    name: str,
    target: str,
    canonical_api,
    candidate_api,
    canonical: dict,
    candidate: dict,
) -> dict:
    raw_changed = (
        canonical.get("md5Checksum") != candidate.get("md5Checksum")
        or int(canonical.get("size", -1)) != int(candidate.get("size", -2))
    )
    canonical_payload = _download_json(canonical_api, str(canonical["id"]))
    candidate_payload = _download_json(candidate_api, str(candidate["id"]))
    canonical_material = _material_fingerprint(canonical_payload)
    candidate_material = _material_fingerprint(candidate_payload)
    material_changed = canonical_material != candidate_material
    return {
        "name": name,
        "target": target,
        # Backward-compatible field now means a governed/material change that
        # warrants promotion, not a timestamp-only byte difference.
        "changed": material_changed,
        "material_changed": material_changed,
        "raw_changed": raw_changed,
        "canonical_md5": canonical.get("md5Checksum"),
        "candidate_md5": candidate.get("md5Checksum"),
        "canonical_material_fingerprint": canonical_material,
        "candidate_material_fingerprint": candidate_material,
        "volatile_only_difference": raw_changed and not material_changed,
    }


def compare_shadow_controls_to_canonical(*, reader_api, writer_api, shadow: dict) -> list[dict]:
    control_folder_id = str((shadow.get("control_bundle") or {}).get("folder_id") or "")
    if not control_folder_id:
        raise RuntimeError("POST_COMMIT_SHADOW_CONTROL_FOLDER_MISSING")

    staged = _staging_control_map(writer_api, control_folder_id)
    folders = _baseline_runtime_children(reader_api)
    manifest_items = _list_children(reader_api, str(folders["00_MANIFESTS"]["id"]))
    semantic_items = _list_children(reader_api, BEHAVIOR_CONTROL_FOLDER_DRIVE_ID)

    rows: list[dict] = []
    for name in DATA_PLANE_CONTROL_FILE_NAMES:
        rows.append(
            _control_diff_row(
                name=name,
                target="DATA_PLANE",
                canonical_api=reader_api,
                candidate_api=writer_api,
                canonical=_exact_named(manifest_items, name),
                candidate=staged[name],
            )
        )
    for name in SEMANTIC_CONTROL_FILE_NAMES:
        rows.append(
            _control_diff_row(
                name=name,
                target="SEMANTIC_CONTROL",
                canonical_api=reader_api,
                candidate_api=writer_api,
                canonical=_exact_named(semantic_items, name),
                candidate=staged[name],
            )
        )
    return rows


def run_post_commit_readback() -> dict:
    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)

    _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    _assert_folder(reader_api, BEHAVIOR_CONTROL_FOLDER_DRIVE_ID, BEHAVIOR_CONTROL_FOLDER_NAME)
    _assert_folder(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, PARITY_STAGING_FOLDER_NAME)

    _, _, persistent_before = baseline_controls(reader_api)
    baseline_before = persistent_state_fingerprint(persistent_before)
    controls_before = canonical_control_snapshot(reader_api)

    shadow = run_governed_delta_machine(mode="SHADOW")
    if shadow.get("pass") is not True or shadow.get("status") != "SHADOW_COMMIT_READY":
        raise RuntimeError("POST_COMMIT_MACHINE_DID_NOT_REACH_SHADOW_COMMIT_READY")
    if (shadow.get("classification") or {}).get("holds"):
        raise RuntimeError("POST_COMMIT_MACHINE_CLASSIFICATION_HOLD")
    if shadow.get("semantic_runtime_status") != "AVAILABLE":
        raise RuntimeError("POST_COMMIT_SEMANTIC_RUNTIME_NOT_AVAILABLE")
    if shadow.get("semantic_runtime_holds"):
        raise RuntimeError("POST_COMMIT_SEMANTIC_RUNTIME_HOLD")

    _, _, persistent_after = baseline_controls(reader_api)
    baseline_after = persistent_state_fingerprint(persistent_after)
    controls_after = canonical_control_snapshot(reader_api)

    if baseline_before != baseline_after:
        raise RuntimeError("POST_COMMIT_CANONICAL_BASELINE_MUTATED_DURING_SHADOW")
    if controls_before["fingerprint"] != controls_after["fingerprint"]:
        raise RuntimeError("POST_COMMIT_CANONICAL_CONTROLS_MUTATED_DURING_SHADOW")

    control_diffs = compare_shadow_controls_to_canonical(
        reader_api=reader_api,
        writer_api=writer_api,
        shadow=shadow,
    )
    source_ops = shadow.get("canonical_commit_operations") or {}
    pending_source_changes = bool(
        (source_ops.get("purge_before_upsert") or [])
        or (source_ops.get("upsert_processed_sources") or [])
    )
    pending_control_changes = [row for row in control_diffs if row["material_changed"]]
    volatile_only_control_differences = [
        row for row in control_diffs if row["volatile_only_difference"]
    ]

    evidence_folder_id = _create_folder(
        writer_api,
        parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        name=f"POST_COMMIT_READBACK_{_stamp()}_{str(shadow.get('github_sha') or '')[:12]}",
    )
    result = {
        "pass": True,
        "schema": POST_COMMIT_SCHEMA,
        "gate": POST_COMMIT_NAME,
        "status": "POST_COMMIT_GOVERNED_READBACK_PASS",
        "canonical_baseline_consumed": True,
        "canonical_controls_stable_during_shadow": True,
        "canonical_write_performed": False,
        "raw_write_performed": False,
        "baseline_state_fingerprint": baseline_after,
        "canonical_control_snapshot_fingerprint": controls_after["fingerprint"],
        "shadow_run_folder_id": shadow.get("run_folder_id"),
        "shadow_run_key": shadow.get("run_key"),
        "shadow_refresh_id": shadow.get("refresh_id"),
        "classification": shadow.get("classification"),
        "semantic_scheduler_status": shadow.get("semantic_scheduler_status"),
        "semantic_work_item_count": shadow.get("semantic_work_item_count"),
        "semantic_backlog_state": shadow.get("semantic_backlog_state"),
        "pending_source_changes": pending_source_changes,
        "pending_control_changes": pending_control_changes,
        "volatile_only_control_differences": volatile_only_control_differences,
        "pending_canonical_change": pending_source_changes or bool(pending_control_changes),
        "activation_candidate": True,
        "unattended_scheduling_authorized": False,
        "next_stage": "GOVERNED_AUTOMATION_ACTIVATION",
        "note": (
            "The permanent machine consumed the canonicalized baseline and completed its normal SHADOW path without mutating canonical state. "
            "Promotion is requested only for material source/control state changes; refresh/timestamp-only byte drift remains audit evidence and does not cause a canonical write loop."
        ),
    }
    upload = upload_json_payload(
        writer_api,
        parent_id=evidence_folder_id,
        name=POST_COMMIT_RESULT,
        payload=result,
    )
    if not upload.get("pass"):
        raise RuntimeError("POST_COMMIT_RESULT_UPLOAD_RECONCILIATION_FAILED")
    result["evidence_folder_id"] = evidence_folder_id
    result["result_upload"] = upload
    return result


def main() -> int:
    result = run_post_commit_readback()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
