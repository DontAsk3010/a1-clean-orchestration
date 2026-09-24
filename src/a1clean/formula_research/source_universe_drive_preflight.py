from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ..google_drive import build_drive_api
from ..source_parity import _baseline_runtime_children, _download_json, _exact_named, _list_children
from .source_universe_cli import _atomic_write, _sha256
from .source_universe_manifest import (
    HISTORICAL_BASELINE_SOURCE_NAMES,
    build_source_universe_manifest,
    manifest_digest_is_valid,
)


def build_from_current_drive_controls(
    *,
    authority_lock_path: Path,
    discovery_time_utc: str | None = None,
) -> dict:
    lock = json.loads(authority_lock_path.read_text(encoding="utf-8"))
    if lock.get("status") != "ACTIVE":
        raise RuntimeError("SOURCE_UNIVERSE_ACTIVE_AUTHORITY_LOCK_NOT_ACTIVE")
    if lock.get("prestart_completeness_gate_required") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_PRESTART_LOCK_REQUIRED")
    if lock.get("dynamic_source_universe_required") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_DYNAMIC_LOCK_REQUIRED")
    if lock.get("fixed_source_count_as_invariant_forbidden") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_FIXED_COUNT_PROHIBITION_REQUIRED")

    api = build_drive_api(read_write=False)
    folders = _baseline_runtime_children(api)
    manifest_items = _list_children(api, folders["00_MANIFESTS"]["id"])
    global_manifest = _download_json(
        api, _exact_named(manifest_items, "GLOBAL_DATA_PLANE_MANIFEST.json")["id"]
    )
    discovery = _download_json(
        api, _exact_named(manifest_items, "GLOBAL_SOURCE_DISCOVERY.json")["id"]
    )
    stamp = discovery_time_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = build_source_universe_manifest(
        global_manifest=global_manifest,
        discovery=discovery,
        authority_revision="sha256:" + _sha256(authority_lock_path),
        discovery_time_utc=stamp,
        required_source_names=HISTORICAL_BASELINE_SOURCE_NAMES,
    )
    if not manifest_digest_is_valid(manifest):
        raise RuntimeError("SOURCE_UNIVERSE_MANIFEST_SELF_DIGEST_FAIL")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--authority-lock",
        type=Path,
        default=Path("governance/a1-clean-active-authority-lock.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discovery-time-utc")
    args = parser.parse_args()
    manifest = build_from_current_drive_controls(
        authority_lock_path=args.authority_lock,
        discovery_time_utc=args.discovery_time_utc,
    )
    _atomic_write(args.output, manifest)
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "status": manifest["status"],
                "source_count": manifest["source_count"],
                "manifest_digest": manifest["manifest_digest"],
                "hold_count": len(manifest["holds"]),
            },
            sort_keys=True,
        )
    )
    return 0 if manifest["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
