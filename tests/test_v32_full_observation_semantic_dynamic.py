from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from a1clean.formula_research.v32_full_observation_semantic_dynamic import (
    SCHEMA,
    checkpoint_is_exact_source_compatible,
)


ROLES = (
    "ticker_days",
    "formation_runs",
    "event_journeys",
    "phase_context",
    "full_observation_envelope",
    "regular_behavior_stream",
    "behavior_day_profiles",
    "behavior_lifecycle",
    "behavior_paths",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, dict, str]:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    outputs = {}
    for role in ROLES:
        path = source_dir / f"{role}.jsonl.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write('{"ok":true}\n')
        outputs[role] = {
            "name": path.name,
            "sha256": _sha(path),
            "bytes": path.stat().st_size,
        }
    revision = "SEMANTIC-REV"
    src = {
        "source_name": "Raw Jun 01-30-2026.csv",
        "source_drive_id": "drive-19",
        "source_sha256": "raw-sha-19",
        "ticker_days": 123,
        "source_rows": 456,
        "regular_rows": 400,
        "nonregular_rows": 56,
    }
    cp = {
        "schema": SCHEMA,
        "status": "PASS",
        "source": src["source_name"],
        "software_revision": revision,
        "source_drive_id": src["source_drive_id"],
        "source_sha256": src["source_sha256"],
        "ticker_days": src["ticker_days"],
        "source_rows": src["source_rows"],
        "regular_rows": src["regular_rows"],
        "nonregular_rows": src["nonregular_rows"],
        "envelope_digest_sha256": "OLD-GLOBAL-UNIVERSE-DIGEST",
        "output_files": outputs,
    }
    cp_path = source_dir / "checkpoint.json"
    cp_path.write_text(json.dumps(cp), encoding="utf-8")
    return cp_path, src, revision


def test_exact_source_checkpoint_reuse_ignores_obsolete_global_universe_digest(tmp_path: Path):
    cp_path, src, revision = _fixture(tmp_path)
    assert checkpoint_is_exact_source_compatible(cp_path, src, revision) is True


def test_source_digest_drift_invalidates_reuse(tmp_path: Path):
    cp_path, src, revision = _fixture(tmp_path)
    src["source_sha256"] = "changed"
    assert checkpoint_is_exact_source_compatible(cp_path, src, revision) is False


def test_output_artifact_drift_invalidates_reuse(tmp_path: Path):
    cp_path, src, revision = _fixture(tmp_path)
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    target = cp_path.parent / cp["output_files"]["behavior_paths"]["name"]
    target.write_bytes(target.read_bytes() + b"drift")
    assert checkpoint_is_exact_source_compatible(cp_path, src, revision) is False
