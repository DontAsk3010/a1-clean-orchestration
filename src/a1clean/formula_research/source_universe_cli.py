from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .source_universe_manifest import (
    HISTORICAL_BASELINE_SOURCE_NAMES,
    build_source_universe_manifest,
    manifest_digest_is_valid,
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_from_control_files(
    *,
    global_manifest_path: Path,
    discovery_path: Path,
    authority_lock_path: Path,
    discovery_time_utc: str,
    require_historical_baseline: bool = True,
) -> dict[str, Any]:
    lock = _load(authority_lock_path)
    if lock.get("status") != "ACTIVE":
        raise RuntimeError("SOURCE_UNIVERSE_ACTIVE_AUTHORITY_LOCK_NOT_ACTIVE")
    if lock.get("dynamic_source_universe_required") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_DYNAMIC_SOURCE_LOCK_REQUIRED")
    if lock.get("fixed_source_count_as_invariant_forbidden") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_FIXED_COUNT_PROHIBITION_REQUIRED")
    required = HISTORICAL_BASELINE_SOURCE_NAMES if require_historical_baseline else ()
    manifest = build_source_universe_manifest(
        global_manifest=_load(global_manifest_path),
        discovery=_load(discovery_path),
        authority_revision="sha256:" + _sha256(authority_lock_path),
        discovery_time_utc=discovery_time_utc,
        required_source_names=required,
    )
    if not manifest_digest_is_valid(manifest):
        raise RuntimeError("SOURCE_UNIVERSE_MANIFEST_SELF_DIGEST_FAIL")
    return manifest


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--global-data-plane-manifest", type=Path, required=True)
    parser.add_argument("--source-discovery", type=Path, required=True)
    parser.add_argument("--authority-lock", type=Path, default=Path("governance/a1-clean-active-authority-lock.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discovery-time-utc", required=True)
    parser.add_argument("--allow-without-historical-baseline", action="store_true")
    args = parser.parse_args()

    manifest = build_from_control_files(
        global_manifest_path=args.global_data_plane_manifest,
        discovery_path=args.source_discovery,
        authority_lock_path=args.authority_lock,
        discovery_time_utc=args.discovery_time_utc,
        require_historical_baseline=not args.allow_without_historical_baseline,
    )
    _atomic_write(args.output, manifest)
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "status": manifest["status"],
                "source_count": manifest["source_count"],
                "manifest_digest": manifest["manifest_digest"],
                "holds": manifest["holds"],
            },
            sort_keys=True,
        )
    )
    return 0 if manifest["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
