from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from .config import FROZEN_RAW_FOLDER_DRIVE_ID
from .google_drive import build_drive_api


def _md5_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def list_canonical_drive_sources(api, folder_id: str) -> list[dict]:
    files: list[dict] = []
    page_token = None
    while True:
        result = (
            api.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken,files(id,name,size,md5Checksum,modifiedTime,mimeType)",
                pageSize=1000,
                pageToken=page_token,
                orderBy="name",
            )
            .execute()
        )
        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return [f for f in files if f.get("mimeType") != "application/vnd.google-apps.folder"]


def compare_local_sources(local_dir: Path, drive_files: Iterable[dict]) -> dict:
    local_dir = Path(local_dir).expanduser().resolve()
    local_files = {p.name: p for p in local_dir.iterdir() if p.is_file()}
    drive_by_name = {str(f["name"]): dict(f) for f in drive_files}

    required: list[dict] = []
    failed = False
    for name in sorted(drive_by_name):
        remote = drive_by_name[name]
        local = local_files.get(name)
        row = {
            "name": name,
            "drive_id": remote.get("id"),
            "drive_size": int(remote["size"]) if remote.get("size") is not None else None,
            "local_path": str(local) if local else None,
            "local_size": local.stat().st_size if local else None,
            "drive_md5": remote.get("md5Checksum"),
            "local_md5": None,
            "status": None,
        }
        if local is None:
            row["status"] = "HOLD_LOCAL_MISSING"
            failed = True
        elif row["drive_size"] is None or row["local_size"] != row["drive_size"]:
            row["status"] = "HOLD_SIZE_MISMATCH"
            failed = True
        elif row["drive_md5"]:
            row["local_md5"] = _md5_file(local)
            if row["local_md5"].lower() != str(row["drive_md5"]).lower():
                row["status"] = "HOLD_CHECKSUM_MISMATCH"
                failed = True
            else:
                row["status"] = "PASS_EXACT_MD5"
        else:
            row["status"] = "HOLD_REMOTE_CHECKSUM_UNAVAILABLE"
            failed = True
        required.append(row)

    extras = sorted(set(local_files) - set(drive_by_name))
    duplicate_drive_names = sorted(
        name for name in {str(f.get("name")) for f in drive_files}
        if sum(1 for f in drive_files if str(f.get("name")) == name) > 1
    )
    if duplicate_drive_names:
        failed = True

    return {
        "pass": not failed,
        "local_dir": str(local_dir),
        "canonical_source_count": len(drive_by_name),
        "local_file_count": len(local_files),
        "required_sources": required,
        "extra_local_files": extras,
        "duplicate_drive_names": duplicate_drive_names,
        "note": "Canonical Drive listing controls the required source universe. Extra local files are reported but never promoted automatically.",
    }


def run_source_preflight(local_dir: str | Path | None = None, folder_id: str | None = None) -> dict:
    raw_dir = Path(local_dir or os.environ["A1_RAW_DIR"]).expanduser().resolve()
    canonical_folder_id = folder_id or os.environ.get(
        "A1_RAW_FOLDER_DRIVE_ID", FROZEN_RAW_FOLDER_DRIVE_ID
    )
    api = build_drive_api()
    drive_files = list_canonical_drive_sources(api, canonical_folder_id)
    report = compare_local_sources(raw_dir, drive_files)
    report["canonical_folder_drive_id"] = canonical_folder_id
    return report


def main() -> int:
    report = run_source_preflight()
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
