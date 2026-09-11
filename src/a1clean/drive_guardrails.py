from __future__ import annotations

import io
import json
from datetime import datetime, timezone

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from .config import (
    CANONICAL_CURRENT_FOLDER_NAME,
    CANONICAL_RAW_FOLDER_NAME,
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    FROZEN_RAW_FOLDER_DRIVE_ID,
    PARITY_STAGING_FOLDER_NAME,
)
from .google_drive import build_drive_api


FOLDER_FIELDS = (
    "id,name,mimeType,parents,capabilities("
    "canAddChildren,canDelete,canEdit,canTrashChildren)"
)


def _folder_snapshot(api, folder_id: str) -> dict:
    return (
        api.files()
        .get(fileId=folder_id, fields=FOLDER_FIELDS, supportsAllDrives=True)
        .execute()
    )


def evaluate_folder_separation(raw: dict, current: dict, staging: dict) -> dict:
    checks: dict[str, dict] = {}

    ids = [raw.get("id"), current.get("id"), staging.get("id")]
    checks["folder_ids_distinct"] = {
        "pass": len(set(ids)) == 3 and all(ids),
        "ids": ids,
    }

    expected = [
        ("raw_identity", raw, CANONICAL_RAW_FOLDER_NAME),
        ("current_identity", current, CANONICAL_CURRENT_FOLDER_NAME),
        ("staging_identity", staging, PARITY_STAGING_FOLDER_NAME),
    ]
    for key, item, expected_name in expected:
        checks[key] = {
            "pass": item.get("name") == expected_name
            and item.get("mimeType") == "application/vnd.google-apps.folder",
            "id": item.get("id"),
            "name": item.get("name"),
            "mimeType": item.get("mimeType"),
        }

    raw_caps = raw.get("capabilities") or {}
    current_caps = current.get("capabilities") or {}
    staging_caps = staging.get("capabilities") or {}

    # Drive file capabilities describe the underlying user's ACL role on the item.
    # They do not prove the OAuth token's effective scope. With the same owner
    # principal, canEdit can remain true even when the reader access token is
    # drive.readonly. Keep RAW/CURRENT ACL capabilities as diagnostics only and
    # prove effective reader no-write separately with a safe probe in STAGING.
    acl_observations = {
        "raw_via_reader": raw_caps,
        "current_via_reader": current_caps,
        "staging_via_writer": staging_caps,
    }

    checks["staging_writer_has_write_capability"] = {
        "pass": bool(staging_caps.get("canAddChildren")),
        "capabilities": staging_caps,
    }

    return {
        "pass": all(row.get("pass") is True for row in checks.values()),
        "checks": checks,
        "acl_observations": acl_observations,
    }


def _probe_media() -> MediaIoBaseUpload:
    return MediaIoBaseUpload(
        io.BytesIO(b"A1 CLEAN parity staging guardrail probe. Safe to delete.\n"),
        mimetype="text/plain",
        resumable=False,
    )


def _reader_staging_write_denial_probe(reader_api, writer_api, staging_folder_id: str) -> dict:
    """Prove the reader channel cannot write, without touching RAW/CURRENT.

    The only attempted write target is PARITY_STAGING. A 401/403 from the reader
    channel is the expected PASS. If a file is unexpectedly created, the writer
    channel immediately removes it and the guardrail fails closed.
    """

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"A1_READER_WRITE_DENIAL_PROBE_{stamp}.txt"
    created_id = None
    try:
        created = (
            reader_api.files()
            .create(
                body={"name": name, "parents": [staging_folder_id]},
                media_body=_probe_media(),
                fields="id,name,parents",
                supportsAllDrives=True,
            )
            .execute()
        )
        created_id = created.get("id")
        cleanup = "NOT_CREATED"
        if created_id:
            try:
                writer_api.files().delete(
                    fileId=created_id, supportsAllDrives=True
                ).execute()
                cleanup = "DELETED_BY_WRITER_AFTER_UNEXPECTED_READER_WRITE"
            except Exception as cleanup_exc:
                cleanup = (
                    f"CLEANUP_FAILED:{type(cleanup_exc).__name__}:{cleanup_exc}"
                )
        return {
            "pass": False,
            "write_denied": False,
            "unexpected_reader_write_succeeded": True,
            "created_id": created_id,
            "created_name": created.get("name"),
            "cleanup": cleanup,
        }
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        if status in (401, 403):
            return {
                "pass": True,
                "write_denied": True,
                "http_status": status,
                "created_id": None,
            }
        return {
            "pass": False,
            "write_denied": False,
            "http_status": status,
            "created_id": None,
            "error": f"HttpError:{exc}",
        }
    except Exception as exc:
        return {
            "pass": False,
            "write_denied": False,
            "created_id": created_id,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _staging_create_delete_probe(api, staging_folder_id: str) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"A1_PARITY_STAGING_WRITE_PROBE_{stamp}.txt"
    created_id = None
    try:
        created = (
            api.files()
            .create(
                body={"name": name, "parents": [staging_folder_id]},
                media_body=_probe_media(),
                fields="id,name,parents",
                supportsAllDrives=True,
            )
            .execute()
        )
        created_id = created.get("id")
        parent_ok = staging_folder_id in (created.get("parents") or [])
        if not created_id or not parent_ok:
            return {
                "pass": False,
                "created_id": created_id,
                "created_name": created.get("name"),
                "error": "Probe create did not reconcile to the governed staging parent.",
            }
        api.files().delete(fileId=created_id, supportsAllDrives=True).execute()
        return {
            "pass": True,
            "created_id": created_id,
            "created_name": created.get("name"),
            "cleanup": "DELETED",
        }
    except Exception as exc:
        cleanup = "NOT_CREATED"
        if created_id:
            try:
                api.files().delete(fileId=created_id, supportsAllDrives=True).execute()
                cleanup = "DELETED_AFTER_ERROR"
            except Exception as cleanup_exc:
                cleanup = f"CLEANUP_FAILED:{type(cleanup_exc).__name__}:{cleanup_exc}"
        return {
            "pass": False,
            "created_id": created_id,
            "cleanup": cleanup,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_drive_guardrail_preflight(*, write_probe: bool = True) -> dict:
    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)

    raw = _folder_snapshot(reader_api, FROZEN_RAW_FOLDER_DRIVE_ID)
    current = _folder_snapshot(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID)
    staging = _folder_snapshot(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID)

    report = evaluate_folder_separation(raw, current, staging)
    report["credential_channels"] = {
        "raw_and_current": "READER_CREDENTIAL / DRIVE_READONLY_SCOPE",
        "parity_staging": "WRITER_CREDENTIAL / DRIVE_WRITE_SCOPE",
    }
    report["folders"] = {
        "raw_via_reader": raw,
        "current_via_reader": current,
        "staging_via_writer": staging,
    }

    if write_probe:
        if report["pass"]:
            reader_probe = _reader_staging_write_denial_probe(
                reader_api, writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
            )
        else:
            reader_probe = {
                "pass": False,
                "skipped": True,
                "reason": "Folder identity/staging capability checks did not pass.",
            }
        report["reader_write_denial_probe_in_staging"] = reader_probe
        report["pass"] = report["pass"] and reader_probe.get("pass") is True

        if report["pass"]:
            writer_probe = _staging_create_delete_probe(
                writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
            )
        else:
            writer_probe = {
                "pass": False,
                "skipped": True,
                "reason": "Reader no-write proof did not pass; writer probe not attempted.",
            }
        report["staging_writer_create_delete_probe"] = writer_probe
        report["pass"] = report["pass"] and writer_probe.get("pass") is True

    report["note"] = (
        "RAW and governed CURRENT are read only through the reader credential; no write is attempted against either folder. "
        "Drive capabilities are ACL observations and may show owner/editor rights even for a readonly OAuth token. "
        "Effective reader no-write is proven only by a denied create attempt in PARITY_STAGING. "
        "The writer channel then performs one tiny create/delete probe in PARITY_STAGING."
    )
    return report


def main() -> int:
    report = run_drive_guardrail_preflight(write_probe=True)
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
