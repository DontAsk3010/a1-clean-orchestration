from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_PATHS = (
    ROOT / ".github/workflows/windows-v32-full-observation-behavior.yml",
    ROOT / ".github/workflows/windows-v32-behavior-grouping-atlas.yml",
    ROOT / "src/a1clean/formula_research/source_universe_manifest.py",
    ROOT / "src/a1clean/formula_research/source_universe_drive_preflight.py",
    ROOT / "src/a1clean/formula_research/v32_dynamic_prestart.py",
    ROOT / "src/a1clean/formula_research/v32_observation_envelope_dynamic.py",
    ROOT / "src/a1clean/formula_research/v32_full_observation_semantic_dynamic.py",
    ROOT / "src/a1clean/formula_research/v32_behavior_grouping_dynamic.py",
)

FORBIDDEN_COMPLETION_FRAGMENTS = (
    "source_count_consumed -ne 18",
    "source_count_consumed != 18",
    "len(sources) != 18",
    "EXPECTED_FULL_SOURCE_COUNT = 18",
    "required_source_count -ne 18",
    "source_count -ne 18",
    "source_count != 18",
)


def test_active_machine2_path_has_no_fixed_18_completion_invariant():
    offenders: list[str] = []
    for path in ACTIVE_PATHS:
        text = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_COMPLETION_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.relative_to(ROOT)}::{fragment}")
    assert offenders == []


def test_active_workflows_execute_dynamic_runners():
    full = (ROOT / ".github/workflows/windows-v32-full-observation-behavior.yml").read_text(encoding="utf-8")
    grouping = (ROOT / ".github/workflows/windows-v32-behavior-grouping-atlas.yml").read_text(encoding="utf-8")
    assert "a1clean.formula_research.source_universe_drive_preflight" in full
    assert "a1clean.formula_research.v32_dynamic_prestart" in full
    assert "a1clean.formula_research.v32_full_observation_semantic_dynamic" in full
    assert "a1clean.formula_research.source_universe_drive_preflight" in grouping
    assert "a1clean.formula_research.v32_dynamic_prestart" in grouping
    assert "a1clean.formula_research.v32_behavior_grouping_dynamic" in grouping
