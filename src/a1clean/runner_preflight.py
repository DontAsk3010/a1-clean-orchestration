from __future__ import annotations

from pathlib import Path
import json
import os
import platform
import shutil
import sys

from .config import DataPlaneConfig

CANONICAL_CURRENT_NAME = "UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT"


def run_preflight() -> dict:
    cfg = DataPlaneConfig.from_env()
    checks: dict[str, dict] = {}

    checks["python"] = {
        "pass": sys.version_info >= (3, 11),
        "version": platform.python_version(),
    }
    checks["raw_dir"] = {
        "pass": cfg.raw_dir.is_dir(),
        "path": str(cfg.raw_dir),
    }
    cfg.run_root.mkdir(parents=True, exist_ok=True)
    checks["staging_not_canonical_current"] = {
        "pass": cfg.run_root.name != CANONICAL_CURRENT_NAME,
        "path": str(cfg.run_root),
    }
    try:
        raw_resolved = cfg.raw_dir.resolve()
        run_resolved = cfg.run_root.resolve()
        disjoint = raw_resolved != run_resolved and raw_resolved not in run_resolved.parents
    except OSError:
        disjoint = False
    checks["staging_not_inside_raw"] = {
        "pass": disjoint,
        "raw": str(cfg.raw_dir),
        "staging": str(cfg.run_root),
    }
    probe = cfg.run_root / ".a1_preflight_write_probe"
    try:
        probe.write_text("preflight", encoding="utf-8")
        probe.unlink(missing_ok=True)
        writable = True
    except OSError as exc:
        writable = False
        checks["staging_writable"] = {"pass": False, "error": str(exc)}
    else:
        checks["staging_writable"] = {"pass": writable}

    usage = shutil.disk_usage(cfg.run_root)
    checks["disk_observation"] = {
        "pass": True,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "note": "Observation only; no invented resource threshold is enforced.",
    }

    try:
        import google.auth
        from googleapiclient.discovery import build
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
        api = build("drive", "v3", credentials=creds, cache_discovery=False)
        result = api.files().list(
            q=f"'{cfg.raw_folder_drive_id}' in parents and trashed=false",
            fields="files(id,name,size,modifiedTime)",
            pageSize=1,
        ).execute()
        drive_ok = isinstance(result.get("files", []), list)
        checks["drive_readonly_identity_access"] = {
            "pass": drive_ok,
            "raw_folder_drive_id": cfg.raw_folder_drive_id,
        }
    except Exception as exc:
        checks["drive_readonly_identity_access"] = {
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    passed = all(v.get("pass") is True for k, v in checks.items() if k != "disk_observation")
    return {"pass": passed, "checks": checks}


def main() -> int:
    report = run_preflight()
    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
