from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaIoBaseUpload

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
    upload_json_payload,
)
from .delta_machine import run_governed_delta_machine
from .google_drive import build_drive_api
from .source_parity import (
    FOLDER_MIME,
    _assert_folder,
    _baseline_runtime_children,
    _create_folder,
    _download_bytes,
    _list_children,
)

PROMOTION_SCHEMA = "A1_GOVERNED_CANONICAL_PROMOTION_V1"
PROMOTION_NAME = "A1_CLEAN_GOVERNED_CANONICAL_PROMOTION"
PREPARE = "PREPARE"
CANONICAL = "CANONICAL"
AUTH_PHRASE = "AUTHORIZE_GATE_G_CANONICAL_COMMIT"
RESULT_NAME = "CANONICAL_PROMOTION_RESULT.json"
PLAN_NAME = "CANONICAL_PROMOTION_PLAN.json"
ROLLBACK_NAME = "ROLLBACK"


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _exact(items: list[dict], name: str, *, allow_missing: bool = False) -> dict | None:
    matches = [row for row in items if row.get("name") == name and row.get("mimeType") != FOLDER_MIME]
    if not matches and allow_missing:
        return None
    if len(matches) != 1:
        raise RuntimeError(f"PROMOTION_FILE_CARDINALITY:{name}:{len(matches)}")
    return matches[0]


def _copy_file(api, *, file_id: str, parent_id: str, name: str) -> dict:
    return (
        api.files()
        .copy(
            fileId=file_id,
            body={"name": name, "parents": [parent_id]},
            fields="id,name,size,md5Checksum,parents,mimeType",
            supportsAllDrives=True,
        )
        .execute()
    )


def _delete_file(api, file_id: str) -> None:
    api.files().delete(fileId=file_id, supportsAllDrives=True).execute()


def _create_bytes_file(api, *, parent_id: str, name: str, data: bytes, mime_type: str) -> dict:
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    return (
        api.files()
        .create(
            body={"name": name, "parents": [parent_id]},
            media_body=media,
            fields="id,name,size,md5Checksum,parents,mimeType",
            supportsAllDrives=True,
        )
        .execute()
    )


def _update_bytes_file(api, *, file_id: str, data: bytes, mime_type: str) -> dict:
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
    return (
        api.files()
        .update(
            fileId=file_id,
            media_body=media,
            fields="id,name,size,md5Checksum,parents,mimeType",
            supportsAllDrives=True,
        )
        .execute()
    )


def _target_prefix_match(name: str, *, source_name: str, logical_folder: str) -> bool:
    stem = Path(source_name).stem
    if logical_folder == "00_MANIFESTS":
        return name in {
            f"{stem}__DATA_PLANE_MANIFEST.json",
            f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json",
        }
    if logical_folder == "01_ACCESS_SHARDS":
        return name.startswith(f"{stem}__PHYSICAL_") and name.endswith(".bin")
    if logical_folder == "02_SEMANTIC_BUNDLES":
        return name.startswith(f"{stem}__SEMANTIC_") and name.endswith(".jsonl")
    if logical_folder == "03_MARKET_DAY_INDEX":
        return name == f"{stem}__MARKET_DAY_INDEX.json"
    raise RuntimeError(f"UNSUPPORTED_CANONICAL_ARTIFACT_FAMILY:{logical_folder}")


def _artifact_snapshot(api, *, parent_id: str, source_name: str, logical_folder: str) -> list[dict]:
    return [
        row
        for row in _list_children(api, parent_id)
        if row.get("mimeType") != FOLDER_MIME
        and _target_prefix_match(str(row.get("name") or ""), source_name=source_name, logical_folder=logical_folder)
    ]


def _fingerprint_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        [
            {
                "name": row.get("name"),
                "size": int(row["size"]) if row.get("size") is not None else None,
                "md5": row.get("md5Checksum"),
            }
            for row in rows
        ],
        key=lambda row: str(row.get("name") or ""),
    )


def _reconcile_family(api, *, canonical_parent_id: str, staging_parent_id: str, source_name: str, logical_folder: str) -> dict:
    canonical = _artifact_snapshot(
        api,
        parent_id=canonical_parent_id,
        source_name=source_name,
        logical_folder=logical_folder,
    )
    staging = [row for row in _list_children(api, staging_parent_id) if row.get("mimeType") != FOLDER_MIME]
    return {
        "logical_folder": logical_folder,
        "source_name": source_name,
        "pass": _fingerprint_rows(canonical) == _fingerprint_rows(staging),
        "canonical": _fingerprint_rows(canonical),
        "staging": _fingerprint_rows(staging),
    }


def _backup_then_delete_source_family(
    api,
    *,
    canonical_parent_id: str,
    rollback_parent_id: str,
    source_name: str,
    logical_folder: str,
    journal: dict,
) -> None:
    family_backup_id = _create_folder(
        api,
        parent_id=rollback_parent_id,
        name=f"{Path(source_name).stem}__{logical_folder}",
    )
    rows = _artifact_snapshot(
        api,
        parent_id=canonical_parent_id,
        source_name=source_name,
        logical_folder=logical_folder,
    )
    for row in rows:
        backup = _copy_file(
            api,
            file_id=str(row["id"]),
            parent_id=family_backup_id,
            name=str(row["name"]),
        )
        journal["source_backups"].append(
            {
                "source_name": source_name,
                "logical_folder": logical_folder,
                "original_parent_id": canonical_parent_id,
                "original_file_id": row["id"],
                "original_name": row["name"],
                "backup_file_id": backup["id"],
            }
        )
        _delete_file(api, str(row["id"]))


def _copy_staged_family(
    api,
    *,
    staging_parent_id: str,
    canonical_parent_id: str,
    source_name: str,
    logical_folder: str,
    journal: dict,
) -> None:
    rows = [row for row in _list_children(api, staging_parent_id) if row.get("mimeType") != FOLDER_MIME]
    if not rows:
        raise RuntimeError(f"STAGED_SOURCE_FAMILY_EMPTY:{source_name}:{logical_folder}")
    for row in rows:
        created = _copy_file(
            api,
            file_id=str(row["id"]),
            parent_id=canonical_parent_id,
            name=str(row["name"]),
        )
        journal["source_created"].append(
            {
                "source_name": source_name,
                "logical_folder": logical_folder,
                "file_id": created["id"],
                "name": created["name"],
            }
        )


def _backup_control(api, *, item: dict, rollback_parent_id: str, target_parent_id: str, journal: dict) -> dict:
    backup = _copy_file(
        api,
        file_id=str(item["id"]),
        parent_id=rollback_parent_id,
        name=str(item["name"]),
    )
    row = {
        "name": item["name"],
        "target_parent_id": target_parent_id,
        "original_file_id": item["id"],
        "backup_file_id": backup["id"],
        "created_new": False,
    }
    journal["control_backups"].append(row)
    return row


def _replace_control(
    api,
    *,
    target_parent_id: str,
    staging_item: dict,
    rollback_parent_id: str,
    journal: dict,
) -> dict:
    targets = _list_children(api, target_parent_id)
    existing = _exact(targets, str(staging_item["name"]), allow_missing=True)
    data = _download_bytes(api, str(staging_item["id"]))
    mime_type = str(staging_item.get("mimeType") or "application/json")
    if existing is None:
        created = _create_bytes_file(
            api,
            parent_id=target_parent_id,
            name=str(staging_item["name"]),
            data=data,
            mime_type=mime_type,
        )
        journal["control_backups"].append(
            {
                "name": staging_item["name"],
                "target_parent_id": target_parent_id,
                "original_file_id": None,
                "backup_file_id": None,
                "created_new": True,
                "created_file_id": created["id"],
            }
        )
        result = created
    else:
        _backup_control(
            api,
            item=existing,
            rollback_parent_id=rollback_parent_id,
            target_parent_id=target_parent_id,
            journal=journal,
        )
        result = _update_bytes_file(
            api,
            file_id=str(existing["id"]),
            data=data,
            mime_type=mime_type,
        )
    expected_md5 = staging_item.get("md5Checksum") or _md5_bytes(data)
    actual_md5 = result.get("md5Checksum")
    if actual_md5 != expected_md5 or int(result.get("size", -1)) != len(data):
        raise RuntimeError(f"CONTROL_READBACK_MISMATCH:{staging_item['name']}")
    return result


def _rollback(api, *, journal: dict) -> dict:
    errors: list[dict] = []
    for row in reversed(journal.get("control_backups", [])):
        try:
            if row.get("created_new"):
                file_id = row.get("created_file_id")
                if file_id:
                    _delete_file(api, str(file_id))
            else:
                backup_id = str(row["backup_file_id"])
                data = _download_bytes(api, backup_id)
                meta = (
                    api.files()
                    .get(fileId=backup_id, fields="mimeType", supportsAllDrives=True)
                    .execute()
                )
                _update_bytes_file(
                    api,
                    file_id=str(row["original_file_id"]),
                    data=data,
                    mime_type=str(meta.get("mimeType") or "application/octet-stream"),
                )
        except Exception as exc:  # rollback must continue through all entries
            errors.append({"stage": "CONTROL", "name": row.get("name"), "error": str(exc)})
    for row in reversed(journal.get("source_created", [])):
        try:
            _delete_file(api, str(row["file_id"]))
        except Exception as exc:
            errors.append({"stage": "SOURCE_CREATED", "name": row.get("name"), "error": str(exc)})
    for row in reversed(journal.get("source_backups", [])):
        try:
            _copy_file(
                api,
                file_id=str(row["backup_file_id"]),
                parent_id=str(row["original_parent_id"]),
                name=str(row["original_name"]),
            )
        except Exception as exc:
            errors.append({"stage": "SOURCE_BACKUP", "name": row.get("original_name"), "error": str(exc)})
    return {"pass": not errors, "errors": errors}


def _staging_control_map(api, control_folder_id: str) -> dict[str, dict]:
    items = _list_children(api, control_folder_id)
    names = DATA_PLANE_CONTROL_FILE_NAMES + SEMANTIC_CONTROL_FILE_NAMES
    return {name: _exact(items, name) for name in names}


def _assert_shadow_result(result: dict) -> None:
    if result.get("pass") is not True or result.get("status") != "SHADOW_COMMIT_READY":
        raise RuntimeError("GATE_G_REQUIRES_SHADOW_COMMIT_READY")
    if result.get("semantic_runtime_status") != "AVAILABLE":
        raise RuntimeError("GATE_G_SEMANTIC_RUNTIME_NOT_AVAILABLE")
    if result.get("semantic_runtime_holds"):
        raise RuntimeError("GATE_G_SEMANTIC_RUNTIME_HOLD")
    if not (result.get("control_bundle") or {}).get("pass"):
        raise RuntimeError("GATE_G_CONTROL_BUNDLE_NOT_RECONCILED")
    if (result.get("classification") or {}).get("holds"):
        raise RuntimeError("GATE_G_DELTA_CLASSIFICATION_HOLD")


def _promotion_plan(result: dict, *, mode: str, transaction_folder_id: str) -> dict:
    ops = result.get("canonical_commit_operations") or {}
    return {
        "schema": PROMOTION_SCHEMA,
        "promotion": PROMOTION_NAME,
        "mode": mode,
        "transaction_folder_id": transaction_folder_id,
        "github_sha": result.get("github_sha"),
        "shadow_run_folder_id": result.get("run_folder_id"),
        "shadow_run_key": result.get("run_key"),
        "semantic_input_fingerprint": result.get("semantic_input_fingerprint"),
        "data_plane_state_is_not_semantic_completion": True,
        "raw_write_authorized": False,
        "canonical_current_target": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "semantic_control_target": BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
        "purge_before_upsert": ops.get("purge_before_upsert") or [],
        "upsert_processed_sources": ops.get("upsert_processed_sources") or [],
        "data_plane_controls": list(DATA_PLANE_CONTROL_FILE_NAMES),
        "semantic_controls": list(SEMANTIC_CONTROL_FILE_NAMES),
        "commit_order": ops.get("commit_order") or [],
        "canonical_write_requested": mode == CANONICAL,
        "authorization_phrase_required": mode == CANONICAL,
    }


def run_canonical_promotion(*, mode: str = PREPARE, authorization: str | None = None) -> dict:
    mode = str(mode).upper()
    if mode not in {PREPARE, CANONICAL}:
        raise ValueError(f"Unsupported promotion mode: {mode}")

    # Freshly re-run/reuse the permanent SHADOW machine first. Its run key includes
    # canonical-source, baseline-state and semantic-input fingerprints, so promotion
    # never trusts a stale hand-carried plan.
    shadow = run_governed_delta_machine(mode="SHADOW")
    _assert_shadow_result(shadow)

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    _assert_folder(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, PARITY_STAGING_FOLDER_NAME)
    _assert_folder(reader_api, BEHAVIOR_CONTROL_FOLDER_DRIVE_ID, BEHAVIOR_CONTROL_FOLDER_NAME)

    transaction_folder_id = _create_folder(
        writer_api,
        parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        name=f"GATE_G_PROMOTION_{mode}_{str(shadow.get('refresh_id') or 'UNKNOWN')}_{str(shadow.get('github_sha') or '')[:12]}",
    )
    rollback_folder_id = _create_folder(writer_api, parent_id=transaction_folder_id, name=ROLLBACK_NAME)
    plan = _promotion_plan(shadow, mode=mode, transaction_folder_id=transaction_folder_id)
    plan_upload = upload_json_payload(
        writer_api,
        parent_id=transaction_folder_id,
        name=PLAN_NAME,
        payload=plan,
    )
    if not plan_upload.get("pass"):
        raise RuntimeError("GATE_G_PLAN_PERSIST_FAILED")

    if mode == PREPARE:
        result = {
            "pass": True,
            **plan,
            "status": "CANONICAL_PROMOTION_PREPARED",
            "canonical_write_performed": False,
            "rollback_required": False,
            "next_stage": "GATE_G_CANONICAL_COMMIT_AUTHORIZATION",
            "note": "Production promotion transaction is prepared from a fresh governed SHADOW state; canonical targets remain unchanged.",
        }
        upload_json_payload(writer_api, parent_id=transaction_folder_id, name=RESULT_NAME, payload=result)
        return result

    if authorization != AUTH_PHRASE:
        raise RuntimeError("CANONICAL_COMMIT_AUTHORIZATION_PHRASE_MISSING_OR_INCORRECT")

    current_folders = _baseline_runtime_children(reader_api)
    canonical_folder_ids = {
        name: str(current_folders[name]["id"])
        for name in ("00_MANIFESTS", "01_ACCESS_SHARDS", "02_SEMANTIC_BUNDLES", "03_MARKET_DAY_INDEX")
    }
    control_folder_id = str((shadow.get("control_bundle") or {}).get("folder_id") or "")
    if not control_folder_id:
        raise RuntimeError("GATE_G_SHADOW_CONTROL_FOLDER_MISSING")
    staging_controls = _staging_control_map(writer_api, control_folder_id)
    journal: dict[str, Any] = {
        "source_backups": [],
        "source_created": [],
        "control_backups": [],
    }
    reconciliations: list[dict] = []

    try:
        ops = shadow.get("canonical_commit_operations") or {}
        processed = shadow.get("processed_sources") or {}
        # Purge active derivatives only after copying recoverable backups into the
        # transaction folder. Canonical RAW is never addressed by this module.
        purge_rows = ops.get("purge_before_upsert") or []
        for row in purge_rows:
            source_name = str(row.get("source_name") or "")
            if not source_name:
                raise RuntimeError("GATE_G_PURGE_SOURCE_NAME_MISSING")
            source_rb = _create_folder(
                writer_api,
                parent_id=rollback_folder_id,
                name=f"SOURCE_{Path(source_name).stem}",
            )
            for logical_folder, parent_id in canonical_folder_ids.items():
                _backup_then_delete_source_family(
                    writer_api,
                    canonical_parent_id=parent_id,
                    rollback_parent_id=source_rb,
                    source_name=source_name,
                    logical_folder=logical_folder,
                    journal=journal,
                )

        # Upsert only the source-scoped artifacts produced and reconciled by the
        # same permanent machine in the current SHADOW run.
        for row in ops.get("upsert_processed_sources") or []:
            source_id = str(row.get("source_drive_id") or "")
            source_name = str(row.get("source_name") or "")
            staged = processed.get(source_id)
            if not staged or staged.get("pass") is not True:
                raise RuntimeError(f"GATE_G_PROCESSED_SOURCE_NOT_RECONCILED:{source_name}")
            artifact_folders = staged.get("artifact_folders") or {}
            for logical_folder, canonical_parent_id in canonical_folder_ids.items():
                staging_parent_id = str(artifact_folders.get(logical_folder) or "")
                if not staging_parent_id:
                    raise RuntimeError(f"GATE_G_STAGED_FAMILY_MISSING:{source_name}:{logical_folder}")
                _copy_staged_family(
                    writer_api,
                    staging_parent_id=staging_parent_id,
                    canonical_parent_id=canonical_parent_id,
                    source_name=source_name,
                    logical_folder=logical_folder,
                    journal=journal,
                )
                check = _reconcile_family(
                    writer_api,
                    canonical_parent_id=canonical_parent_id,
                    staging_parent_id=staging_parent_id,
                    source_name=source_name,
                    logical_folder=logical_folder,
                )
                reconciliations.append(check)
                if not check["pass"]:
                    raise RuntimeError(f"GATE_G_SOURCE_POSTWRITE_MISMATCH:{source_name}:{logical_folder}")

        # Data-plane controls preserve existing file IDs when present; semantic
        # ledger/work-queue are created once then updated in place on later commits.
        data_control_target = canonical_folder_ids["00_MANIFESTS"]
        control_rollback = _create_folder(writer_api, parent_id=rollback_folder_id, name="CONTROLS")
        for name in DATA_PLANE_CONTROL_FILE_NAMES:
            _replace_control(
                writer_api,
                target_parent_id=data_control_target,
                staging_item=staging_controls[name],
                rollback_parent_id=control_rollback,
                journal=journal,
            )
        for name in SEMANTIC_CONTROL_FILE_NAMES:
            _replace_control(
                writer_api,
                target_parent_id=BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
                staging_item=staging_controls[name],
                rollback_parent_id=control_rollback,
                journal=journal,
            )

        # Final unique-name + hash/size readback for every promoted control.
        control_checks = []
        for name in DATA_PLANE_CONTROL_FILE_NAMES:
            target = _exact(_list_children(writer_api, data_control_target), name)
            expected = staging_controls[name]
            ok = (
                target.get("md5Checksum") == expected.get("md5Checksum")
                and int(target.get("size", -1)) == int(expected.get("size", -2))
            )
            control_checks.append({"name": name, "target": "DATA_PLANE", "pass": ok})
        for name in SEMANTIC_CONTROL_FILE_NAMES:
            target = _exact(_list_children(writer_api, BEHAVIOR_CONTROL_FOLDER_DRIVE_ID), name)
            expected = staging_controls[name]
            ok = (
                target.get("md5Checksum") == expected.get("md5Checksum")
                and int(target.get("size", -1)) == int(expected.get("size", -2))
            )
            control_checks.append({"name": name, "target": "SEMANTIC_CONTROL", "pass": ok})
        if not all(row["pass"] for row in control_checks):
            raise RuntimeError("GATE_G_CONTROL_POSTWRITE_RECONCILIATION_FAILED")

        # Removed-only sources must be absent from active derivative folders.
        upsert_names = {str(row.get("source_name") or "") for row in ops.get("upsert_processed_sources") or []}
        removed_checks = []
        for row in purge_rows:
            source_name = str(row.get("source_name") or "")
            if source_name in upsert_names:
                continue
            remaining = []
            for logical_folder, parent_id in canonical_folder_ids.items():
                remaining.extend(
                    _artifact_snapshot(
                        writer_api,
                        parent_id=parent_id,
                        source_name=source_name,
                        logical_folder=logical_folder,
                    )
                )
            removed_checks.append({"source_name": source_name, "pass": not remaining})
        if not all(row["pass"] for row in removed_checks):
            raise RuntimeError("GATE_G_REMOVED_SOURCE_STILL_ACTIVE")

        result = {
            "pass": True,
            **plan,
            "status": "CANONICAL_PROMOTION_COMMITTED",
            "canonical_write_performed": True,
            "raw_write_performed": False,
            "source_reconciliations": reconciliations,
            "control_reconciliations": control_checks,
            "removed_source_reconciliations": removed_checks,
            "rollback_required": False,
            "rollback_folder_id": rollback_folder_id,
            "next_stage": "POST_COMMIT_GOVERNED_READBACK_AND_AUTOMATION_ACTIVATION_GATE",
            "readiness": {
                "machine_runtime_ready": True,
                "data_plane_ready": True,
                "semantic_scheduler_ready": True,
                "semantic_research_complete": bool(shadow.get("semantic_complete")),
                "canonical_commit_authorized": True,
                "live_trading_readiness": "NOT_EVALUATED_BY_THIS_MACHINE",
            },
        }
        result_upload = upload_json_payload(
            writer_api,
            parent_id=transaction_folder_id,
            name=RESULT_NAME,
            payload=result,
        )
        if not result_upload.get("pass"):
            raise RuntimeError("GATE_G_RESULT_PERSIST_FAILED")
        result["result_upload"] = result_upload
        return result
    except Exception as exc:
        rollback = _rollback(writer_api, journal=journal)
        failed = {
            "pass": False,
            **plan,
            "status": "HOLD",
            "canonical_write_performed": True,
            "raw_write_performed": False,
            "hold": {"type": type(exc).__name__, "message": str(exc)},
            "rollback": rollback,
            "rollback_required": not rollback.get("pass", False),
            "rollback_folder_id": rollback_folder_id,
        }
        upload_json_payload(writer_api, parent_id=transaction_folder_id, name=RESULT_NAME, payload=failed)
        raise RuntimeError(f"GATE_G_CANONICAL_PROMOTION_HOLD:{exc}; rollback={json.dumps(rollback, sort_keys=True)}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="A1 CLEAN governed canonical promotion")
    parser.add_argument("--mode", choices=[PREPARE, CANONICAL], default=PREPARE)
    parser.add_argument("--authorization", default=os.environ.get("A1_CANONICAL_COMMIT_AUTHORIZATION"))
    args = parser.parse_args()
    result = run_canonical_promotion(mode=args.mode, authorization=args.authorization)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
