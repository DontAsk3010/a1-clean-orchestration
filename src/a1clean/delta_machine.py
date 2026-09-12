from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone

from .config import (
    CANONICAL_CURRENT_FOLDER_NAME,
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    PARITY_STAGING_FOLDER_NAME,
)
from .delta_artifacts import (
    CONTROL_FILE_NAMES,
    baseline_controls,
    persist_control_bundle,
    persist_processed_source,
    process_source_to_local,
    upload_json_payload,
)
from .delta_control import build_control_bundle
from .delta_state import (
    classify_delta_state,
    persistent_state_fingerprint,
    source_row_by_id,
    source_universe_fingerprint,
)
from .google_drive import build_drive_api
from .source_parity import FOLDER_MIME, _assert_folder, _create_folder, _download_json, _list_children
from .source_preflight import run_source_preflight

MACHINE_SCHEMA = "A1_GOVERNED_DELTA_MACHINE_V1"
CHECKPOINT_SCHEMA = "A1_GOVERNED_DELTA_MACHINE_CHECKPOINT_V1"
MACHINE_NAME = "A1_CLEAN_GOVERNED_DELTA_MACHINE"
MACHINE_MODE_SHADOW = "SHADOW"
MACHINE_MODE_CANONICAL = "CANONICAL"
MACHINE_RUN_PREFIX = "GOVERNED_DELTA_MACHINE"
MACHINE_PLAN_NAME = "RUNTIME_COMMIT_PLAN.json"
MACHINE_RESULT_NAME = "DELTA_MACHINE_RESULT.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


def _stamp() -> str:
    return _now().strftime("%Y%m%dT%H%M%SZ")


def _github_sha() -> str:
    return (os.environ.get("GITHUB_SHA") or "LOCAL_NO_GITHUB_SHA").strip() or "LOCAL_NO_GITHUB_SHA"


def _run_key(preflight: dict, persistent: dict) -> str:
    return f"{_github_sha()[:12]}_{source_universe_fingerprint(preflight)[:12]}_{persistent_state_fingerprint(persistent)[:12]}"


def _checkpoint_name(sequence: int, status: str) -> str:
    return f"MACHINE_CHECKPOINT_{sequence:04d}_{_stamp()}_{status}.json"


def _persist_checkpoint(writer_api, checkpoint: dict) -> None:
    result = upload_json_payload(
        writer_api,
        parent_id=str(checkpoint["run_folder_id"]),
        name=_checkpoint_name(int(checkpoint.get("checkpoint_sequence", 0)), str(checkpoint.get("status", "UNKNOWN"))),
        payload=checkpoint,
    )
    if not result.get("pass"):
        raise RuntimeError("DELTA_MACHINE_CHECKPOINT_UPLOAD_RECONCILIATION_FAILED")


def _latest_checkpoint(writer_api, run_folder_id: str) -> dict | None:
    files = sorted(
        [
            item for item in _list_children(writer_api, run_folder_id)
            if item.get("mimeType") != FOLDER_MIME
            and str(item.get("name", "")).startswith("MACHINE_CHECKPOINT_")
            and str(item.get("name", "")).endswith(".json")
        ],
        key=lambda item: str(item.get("name")),
    )
    return _download_json(writer_api, files[-1]["id"]) if files else None


def _validate_checkpoint(checkpoint: dict, *, run_key: str, preflight: dict, persistent: dict, classification: dict) -> None:
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "machine": MACHINE_NAME,
        "mode": MACHINE_MODE_SHADOW,
        "run_key": run_key,
        "github_sha": _github_sha(),
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": source_universe_fingerprint(preflight),
        "baseline_state_fingerprint": persistent_state_fingerprint(persistent),
        "classification": classification,
    }
    for key, value in expected.items():
        if checkpoint.get(key) != value:
            raise RuntimeError(f"DELTA_MACHINE_RESUME_IDENTITY_MISMATCH:{key}")


def _find_or_create_run(writer_api, *, preflight: dict, persistent: dict, classification: dict) -> tuple[dict, bool]:
    run_key = _run_key(preflight, persistent)
    suffix = "_" + run_key
    folders = sorted(
        [
            item for item in _list_children(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID)
            if item.get("mimeType") == FOLDER_MIME
            and str(item.get("name", "")).startswith(MACHINE_RUN_PREFIX + "_")
            and str(item.get("name", "")).endswith(suffix)
        ],
        key=lambda item: str(item.get("name")), reverse=True,
    )
    for folder in folders:
        checkpoint = _latest_checkpoint(writer_api, str(folder["id"]))
        if checkpoint is None:
            continue
        try:
            _validate_checkpoint(checkpoint, run_key=run_key, preflight=preflight, persistent=persistent, classification=classification)
        except RuntimeError:
            continue
        if checkpoint.get("status") in {"IN_PROGRESS", "HOLD", "SHADOW_COMMIT_READY"}:
            return checkpoint, True

    name = f"{MACHINE_RUN_PREFIX}_{_stamp()}_{run_key}"
    folder_id = _create_folder(writer_api, parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, name=name)
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "machine": MACHINE_NAME,
        "mode": MACHINE_MODE_SHADOW,
        "status": "IN_PROGRESS",
        "checkpoint_sequence": 0,
        "run_folder_id": folder_id,
        "run_folder_name": name,
        "run_key": run_key,
        "github_sha": _github_sha(),
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": source_universe_fingerprint(preflight),
        "baseline_state_fingerprint": persistent_state_fingerprint(persistent),
        "canonical_source_count_observed": classification.get("active_source_count"),
        "source_count_is_not_an_invariant": True,
        "refresh_id": _now().strftime("DELTA_%Y%m%d_%H%M%S"),
        "started_at_utc": _iso(),
        "classification": classification,
        "processed_sources": {},
        "current_source": None,
        "next_exact_resume_source": None,
        "hold": None,
        "updated_at_utc": _iso(),
    }
    _persist_checkpoint(writer_api, checkpoint)
    return checkpoint, False


def _commit_operations(classification: dict, baseline_global: dict) -> dict:
    prior = {str(row.get("source_drive_id")): row for row in baseline_global.get("sources", []) if row.get("source_drive_id")}
    purge, seen = [], set()
    for row in classification.get("removed_purged", []):
        sid = str(row.get("source_drive_id") or "")
        old = prior.get(sid) or row
        key = (sid, str(old.get("source_name") or ""))
        if key not in seen:
            seen.add(key)
            purge.append({"source_drive_id": sid, "source_name": old.get("source_name"), "reason": "REMOVED_PURGED"})
    for key_name, reason in (("changed_rebuilt", "CHANGED_REBUILT"), ("replacement_same_content", "REPLACEMENT_SAME_CONTENT")):
        for row in classification.get(key_name, []):
            sid = str(row.get("previous_source_drive_id") or "")
            old = prior.get(sid) or {}
            name = old.get("source_name") or row.get("previous_source_name")
            key = (sid, str(name or ""))
            if sid and key not in seen:
                seen.add(key)
                purge.append({"source_drive_id": sid, "source_name": name, "reason": reason})
    upsert = [
        {"source_drive_id": row.get("source_drive_id"), "source_name": row.get("source_name"), "delta_action": action}
        for key_name, action in (("new_processed", "NEW_PROCESSED"), ("changed_rebuilt", "CHANGED_REBUILT"), ("replacement_same_content", "REPLACEMENT_SAME_CONTENT"))
        for row in classification.get(key_name, [])
    ]
    return {
        "execution_authorized": False,
        "canonical_target": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "purge_before_upsert": purge,
        "upsert_processed_sources": upsert,
        "replace_control_files": list(CONTROL_FILE_NAMES),
        "commit_order": ["PURGE_STALE_SOURCE_SCOPED_DERIVATIVES", "UPSERT_PROCESSED_SOURCE_ARTIFACTS", "RECONCILE_RUNTIME", "ATOMIC_CONTROL_POINTER_COMMIT"],
        "note": "Gate F records the permanent deployment plan only; canonical CURRENT is not mutated.",
    }


def _unique_result(writer_api, run_folder_id: str) -> dict | None:
    matches = [
        item for item in _list_children(writer_api, run_folder_id)
        if item.get("mimeType") != FOLDER_MIME and item.get("name") == MACHINE_RESULT_NAME
    ]
    return _download_json(writer_api, matches[0]["id"]) if len(matches) == 1 else None


def run_governed_delta_machine(*, mode: str = MACHINE_MODE_SHADOW) -> dict:
    """Run the permanent governed delta machine under a governed commit policy.

    Gate F runs this exact production code path in SHADOW. No separate tester
    engine exists. Canonical commit remains deployment-locked until Gate F PASS.
    """
    mode = str(mode).upper()
    if mode not in {MACHINE_MODE_SHADOW, MACHINE_MODE_CANONICAL}:
        raise ValueError(f"Unsupported machine mode: {mode}")
    if mode == MACHINE_MODE_CANONICAL:
        raise RuntimeError("CANONICAL_COMMIT_NOT_AUTHORIZED: Gate F PASS + owner authority required")

    preflight = run_source_preflight()
    if not preflight.get("pass"):
        raise RuntimeError("SOURCE_PREFLIGHT_HOLD: governed delta machine will not continue")

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    _assert_folder(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, PARITY_STAGING_FOLDER_NAME)
    _, baseline_global, baseline_persistent = baseline_controls(reader_api)
    classification = classify_delta_state(preflight=preflight, persistent_state=baseline_persistent)

    checkpoint, resumed = _find_or_create_run(writer_api, preflight=preflight, persistent=baseline_persistent, classification=classification)
    run_folder_id = str(checkpoint["run_folder_id"])
    if checkpoint.get("status") == "SHADOW_COMMIT_READY":
        result = _unique_result(writer_api, run_folder_id)
        if result is None:
            raise RuntimeError("DELTA_MACHINE_READY_CHECKPOINT_WITHOUT_UNIQUE_RESULT")
        result["already_complete"] = True
        result["resumed_existing_run"] = True
        return result

    plan = {
        "schema": MACHINE_SCHEMA,
        "machine": MACHINE_NAME,
        "mode": mode,
        "refresh_id": checkpoint["refresh_id"],
        "started_at_utc": checkpoint["started_at_utc"],
        "run_folder_id": run_folder_id,
        "run_folder_name": checkpoint["run_folder_name"],
        "run_key": checkpoint["run_key"],
        "github_sha": checkpoint["github_sha"],
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "canonical_source_count_observed": classification.get("active_source_count"),
        "source_count_is_not_an_invariant": True,
        "classification": classification,
        "canonical_commit_operations": _commit_operations(classification, baseline_global),
        "canonical_write_policy": {"raw": "READ_ONLY_NEVER_WRITTEN", "current": "READ_ONLY_WHILE_GATE_F_OPEN", "shadow": "PARITY_STAGING_ONLY"},
    }
    if not resumed:
        uploaded = upload_json_payload(writer_api, parent_id=run_folder_id, name=MACHINE_PLAN_NAME, payload=plan)
        if not uploaded.get("pass"):
            raise RuntimeError("DELTA_MACHINE_PLAN_UPLOAD_RECONCILIATION_FAILED")

    if classification.get("holds"):
        checkpoint.update({"status": "HOLD", "hold": {"reason": "DELTA_STATE_CLASSIFICATION_HOLD", "holds": classification["holds"]}, "updated_at_utc": _iso()})
        checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
        _persist_checkpoint(writer_api, checkpoint)
        result = {"pass": False, **plan, "status": "HOLD", "finished_at_utc": _iso(), "processed_sources": checkpoint.get("processed_sources", {})}
        upload_json_payload(writer_api, parent_id=run_folder_id, name=MACHINE_RESULT_NAME, payload=result)
        return result

    source_folders = [item for item in _list_children(writer_api, run_folder_id) if item.get("mimeType") == FOLDER_MIME and item.get("name") == "PROCESSED_SOURCES"]
    if len(source_folders) > 1:
        raise RuntimeError("DELTA_MACHINE_PROCESSED_SOURCES_FOLDER_DUPLICATE")
    sources_folder_id = str(source_folders[0]["id"]) if source_folders else _create_folder(writer_api, parent_id=run_folder_id, name="PROCESSED_SOURCES")

    row_by_id = source_row_by_id(preflight)
    process_rows = sorted(
        list(classification.get("new_processed", [])) + list(classification.get("changed_rebuilt", [])) + list(classification.get("replacement_same_content", [])),
        key=lambda row: (str(row.get("source_name")), str(row.get("source_drive_id"))),
    )
    action_by_id = {
        str(row["source_drive_id"]): action
        for key_name, action in (("new_processed", "NEW_PROCESSED"), ("changed_rebuilt", "CHANGED_REBUILT"), ("replacement_same_content", "REPLACEMENT_SAME_CONTENT"))
        for row in classification.get(key_name, [])
    }
    processed = dict(checkpoint.get("processed_sources", {}))
    checkpoint.update({"status": "IN_PROGRESS", "hold": None})
    try:
        for index, row in enumerate(process_rows, start=1):
            source_id = str(row["source_drive_id"])
            if processed.get(source_id, {}).get("pass") is True:
                print(f"RESUME VERIFIED DELTA SOURCE {index}/{len(process_rows)} | {row['source_name']}")
                continue
            selected = row_by_id.get(source_id)
            if selected is None:
                raise RuntimeError(f"DELTA_MACHINE_PREFLIGHT_ROW_MISSING:{source_id}")
            checkpoint.update({"current_source": selected["name"], "next_exact_resume_source": selected["name"], "updated_at_utc": _iso()})
            checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
            _persist_checkpoint(writer_api, checkpoint)
            print(f"PROCESS DELTA SOURCE {index}/{len(process_rows)} | {selected['name']} | {action_by_id[source_id]}")
            root, engine_result, manifest = process_source_to_local(selected=selected, reader_api=reader_api)
            try:
                persisted = persist_processed_source(
                    writer_api,
                    sources_folder_id=sources_folder_id,
                    source_index=index,
                    source_name=str(selected["name"]),
                    root=root,
                    engine_result=engine_result,
                    source_manifest=manifest,
                    delta_action=action_by_id[source_id],
                    stamp=_stamp(),
                )
            finally:
                shutil.rmtree(root, ignore_errors=True)
            if not persisted.get("pass"):
                raise RuntimeError(f"DELTA_MACHINE_SOURCE_EVIDENCE_UPLOAD_FAILED:{selected['name']}")
            processed[source_id] = persisted
            checkpoint["processed_sources"] = processed
            checkpoint["current_source"] = None
            checkpoint["next_exact_resume_source"] = process_rows[index]["source_name"] if index < len(process_rows) else None
            checkpoint["updated_at_utc"] = _iso()
            checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
            _persist_checkpoint(writer_api, checkpoint)
    except Exception as exc:
        checkpoint.update({"status": "HOLD", "hold": {"type": type(exc).__name__, "message": str(exc)}, "updated_at_utc": _iso()})
        checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
        _persist_checkpoint(writer_api, checkpoint)
        raise

    finished = _iso()
    bundle = build_control_bundle(
        baseline_global=baseline_global,
        baseline_persistent=baseline_persistent,
        preflight=preflight,
        classification=classification,
        processed=processed,
        started_at_utc=checkpoint["started_at_utc"],
        finished_at_utc=finished,
        refresh_id=checkpoint["refresh_id"],
    )
    control_upload = persist_control_bundle(writer_api, run_folder_id=run_folder_id, bundle=bundle, stamp=_stamp())
    if not control_upload.get("pass"):
        raise RuntimeError("DELTA_MACHINE_CONTROL_BUNDLE_UPLOAD_RECONCILIATION_FAILED")

    result = {
        "pass": True,
        **plan,
        "status": "SHADOW_COMMIT_READY",
        "finished_at_utc": finished,
        "processed_sources": processed,
        "control_bundle": control_upload,
        "resumed_existing_run": resumed,
        "next_stage": "GATE_F_DELTA_STATE_TRANSITION_PARITY_RECONCILIATION",
        "note": "Permanent governed delta machine operating under SHADOW commit policy; Gate F validates this same code path, not a separate tester engine.",
    }
    result_upload = upload_json_payload(writer_api, parent_id=run_folder_id, name=MACHINE_RESULT_NAME, payload=result)
    if not result_upload.get("pass"):
        raise RuntimeError("DELTA_MACHINE_RESULT_UPLOAD_RECONCILIATION_FAILED")
    result["result_upload"] = result_upload
    checkpoint.update({"status": "SHADOW_COMMIT_READY", "processed_sources": processed, "current_source": None, "next_exact_resume_source": None, "updated_at_utc": _iso()})
    checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
    _persist_checkpoint(writer_api, checkpoint)
    return result
