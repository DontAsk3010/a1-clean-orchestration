from __future__ import annotations

import json
from pathlib import Path

from a1clean.formula_research.source_universe_manifest import build_source_universe_manifest
from a1clean.formula_research.v32_behavior_grouping_dynamic import (
    configure_source_universe,
    grouping_progress,
)
from a1clean.formula_research import v32_behavior_grouping_atlas as base


def _source(index: int, name: str, first_date: str, last_date: str) -> dict:
    return {
        "source_drive_id": f"id-{index}",
        "source_name": name,
        "source_sha256": f"sha-{index}",
        "status": "PASS",
        "first_observed_date": first_date,
        "first_observed_time": "09:00:00",
        "last_observed_date": last_date,
        "last_observed_time": "16:15:00",
    }


def test_grouping_next_source_and_completion_use_manifest_length(tmp_path: Path):
    rows = [
        _source(1, "A.csv", "2026-01-01", "2026-01-31"),
        _source(2, "B.csv", "2026-02-01", "2026-02-28"),
        _source(3, "C.csv", "2026-03-01", "2026-03-31"),
    ]
    manifest = build_source_universe_manifest(
        global_manifest={"sources": rows, "canonical_source_home_drive_id": "raw"},
        discovery={
            "files": [
                {"drive_file_id": row["source_drive_id"], "name": row["source_name"], "identity_state": "MATCH"}
                for row in rows
            ]
        },
        authority_revision="AUTH",
        discovery_time_utc="2026-09-24T10:00:00Z",
    )
    path = tmp_path / "source-universe-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    _, names = configure_source_universe(path)
    assert names == ("A.csv", "B.csv", "C.csv")
    assert tuple(base.FULL_CHRONOLOGICAL_SOURCE_NAMES) == names

    progress = grouping_progress(names, 2)
    assert progress == {
        "consumed": 2,
        "total": 3,
        "complete": False,
        "next_source": "C.csv",
    }
    complete = grouping_progress(names, 3)
    assert complete["complete"] is True
    assert complete["next_source"] is None


def test_grouping_dynamic_length_can_be_19_not_fixed_18():
    names = tuple(f"source-{i:02d}.csv" for i in range(1, 20))
    progress = grouping_progress(names, 18)
    assert progress["complete"] is False
    assert progress["total"] == 19
    assert progress["next_source"] == "source-19.csv"
