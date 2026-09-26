from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from . import v32_behavior_grouping_atlas as base
from . import v32_behavior_grouping_atlas_v2 as v2
from .source_universe_manifest import (
    assert_historical_baseline_order,
    manifest_digest_is_valid,
    source_names_from_manifest,
)


def load_source_universe_manifest(path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not manifest_digest_is_valid(manifest):
        raise RuntimeError("M2_GROUP_SOURCE_UNIVERSE_MANIFEST_DIGEST_FAIL")
    names = source_names_from_manifest(manifest, require_pass=True)
    assert_historical_baseline_order(names)
    declared = int(manifest.get("source_count", -1))
    if declared != len(names):
        raise RuntimeError(
            f"M2_GROUP_SOURCE_UNIVERSE_COUNT_DRIFT:declared={declared}:actual={len(names)}"
        )
    return manifest, names


def configure_source_universe(path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    manifest, names = load_source_universe_manifest(path)
    # V2 deliberately reuses the proven V1 SQLite contribution engine. The
    # engine's source-order global is rebound from the governed manifest before
    # any checkpoint read, so source prefix, next_source and completion are all
    # dynamic and share one authoritative order.
    base.FULL_CHRONOLOGICAL_SOURCE_NAMES = names
    return manifest, names


def grouping_progress(source_names: tuple[str, ...], consumed_count: int) -> dict[str, Any]:
    total = len(source_names)
    if consumed_count < 0 or consumed_count > total:
        raise RuntimeError(
            f"M2_GROUP_DYNAMIC_PROGRESS_COUNT_INVALID:{consumed_count}:{total}"
        )
    return {
        "consumed": consumed_count,
        "total": total,
        "complete": consumed_count == total,
        "next_source": source_names[consumed_count] if consumed_count < total else None,
    }


def run_once(
    *,
    semantic_root: Path,
    output_root: Path,
    software_revision: str,
    bootstrap_source_count: int,
    source_universe_manifest: Path,
) -> dict[str, Any]:
    source_manifest, names = configure_source_universe(source_universe_manifest)
    result = v2.run_once(
        semantic_root=semantic_root,
        output_root=output_root,
        software_revision=software_revision,
        bootstrap_source_count=bootstrap_source_count,
    )
    progress = grouping_progress(names, int(result.get("source_count_consumed", 0)))
    result["source_universe_manifest_digest"] = source_manifest["manifest_digest"]
    result["source_universe_source_count"] = len(names)
    result["source_universe_dynamic"] = True
    result["dynamic_progress"] = progress
    base._atomic_json(output_root / "manifest.json", result)

    checkpoint_path = output_root / "current-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint.update(
        {
            "source_universe_manifest_digest": source_manifest["manifest_digest"],
            "source_universe_source_count": len(names),
            "source_universe_dynamic": True,
            "next_source": progress["next_source"],
            "complete": progress["complete"],
        }
    )
    base._atomic_json(checkpoint_path, checkpoint)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--source-universe-manifest", type=Path, required=True)
    parser.add_argument("--bootstrap-source-count", type=int, default=8)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.poll_seconds < 60:
        raise RuntimeError("M2_GROUP_WATCH_FREQUENCY_TOO_HIGH")

    _, names = configure_source_universe(args.source_universe_manifest)
    if not 1 <= args.bootstrap_source_count <= len(names):
        raise RuntimeError(
            f"M2_GROUP_INVALID_BOOTSTRAP_SOURCE_COUNT:{args.bootstrap_source_count}:{len(names)}"
        )

    last_count = -1
    while True:
        atlas = run_once(
            semantic_root=args.semantic_root,
            output_root=args.output_root,
            software_revision=args.software_revision,
            bootstrap_source_count=args.bootstrap_source_count,
            source_universe_manifest=args.source_universe_manifest,
        )
        progress = grouping_progress(names, int(atlas["source_count_consumed"]))
        if progress["complete"]:
            print(
                "M2_GROUP_FULL_SOURCE_CONSUMPTION_PASS|"
                f"consumed={progress['consumed']}|total={progress['total']}|"
                f"manifest={atlas['source_universe_manifest_digest']}"
            )
            return
        if not args.watch:
            return
        if progress["consumed"] != last_count:
            print(
                "M2_GROUP_WATCH|"
                f"consumed={progress['consumed']}/{progress['total']}|"
                f"waiting_for_durable_pass={progress['next_source']}"
            )
            last_count = int(progress["consumed"])
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
