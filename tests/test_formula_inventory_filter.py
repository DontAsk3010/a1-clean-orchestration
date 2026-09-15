from __future__ import annotations

import pytest

from a1clean.formula_research.corpus_translate_filtered import is_target_stage1_manifest
from a1clean.formula_research.lane2_translate import (
    EXPECTED_LANE2_PLAN_FINGERPRINT,
    EXPECTED_LANE2_PLAN_ID,
    FormulaTranslationContractError,
)


def test_non_target_governed_plan_is_ignored():
    assert is_target_stage1_manifest(
        {
            "plan_id": "L2_RUNTIME_CERTIFICATION_UNINTERPRETED_V1",
            "plan_fingerprint": "different-governed-plan",
        }
    ) is False


def test_exact_stage1_plan_is_selected():
    assert is_target_stage1_manifest(
        {
            "plan_id": EXPECTED_LANE2_PLAN_ID,
            "plan_fingerprint": EXPECTED_LANE2_PLAN_FINGERPRINT,
        }
    ) is True


def test_target_plan_with_drifted_fingerprint_fails_closed():
    with pytest.raises(FormulaTranslationContractError, match="TARGET_STAGE1_PLAN_FINGERPRINT_MISMATCH"):
        is_target_stage1_manifest(
            {
                "plan_id": EXPECTED_LANE2_PLAN_ID,
                "plan_fingerprint": "drifted",
            }
        )
