from __future__ import annotations

import pytest

from a1clean.formula_research.lane2_translate import (
    EXPECTED_LANE2_PLAN_FINGERPRINT,
    EXPECTED_LANE2_PLAN_ID,
    FormulaTranslationContractError,
    translate_lane2_packet_result,
)
from a1clean.formula_research.readiness import FormulaReadinessInput, assess_formula_readiness


def _readiness(**overrides):
    values = {
        "owner_formula_research_authorized": True,
        "lane2_universe_corpus_complete": True,
        "lane2_hold": False,
        "semantic_corpus_complete": False,
        "cross_ticker_reconciliation_complete": False,
        "cross_date_reconciliation_complete": False,
        "cross_month_atlas_complete": False,
        "current_execution_formula_gate_open": False,
    }
    values.update(overrides)
    return FormulaReadinessInput(**values)


def _stage1_result():
    return {
        "schema": "A1_ALGORITHMIC_PATTERN_DISCOVERY_PACKET_RESULT_V1",
        "packet_identity": {
            "generation_id": "GEN",
            "source_drive_id": "source",
            "source_name": "raw.csv",
            "source_sha256": "abc",
            "trading_date": "2026-05-29",
            "ticker": "TEST",
            "first_clock_time": "09:00:00",
            "last_clock_time": "09:05:00",
            "data_row_count": 6,
            "source_row_first": 10,
            "source_row_last": 15,
        },
        "packet_fingerprint": "packet-fingerprint",
        "plan_id": EXPECTED_LANE2_PLAN_ID,
        "plan_fingerprint": EXPECTED_LANE2_PLAN_FINGERPRINT,
        "independence_assertions": {
            "ai_semantic_labels_consumed": False,
            "ai_event_journey_objects_consumed": False,
            "outcomes_consumed": False,
            "trading_signal_created": False,
            "formula_stage_opened": False,
            "sampling_used": False,
            "synthetic_rows_created": False,
        },
        "reconciliation_status": "ALGORITHMIC_ONLY_NOT_YET_RECONCILED_WITH_AI",
        "runs": [
            {
                "run_id": "r1",
                "tool": "RUPTURES",
                "purpose": "CHANGE_POINT_REGIME_SEGMENTATION_EVIDENCE",
                "field": "RAW_CLOSE",
                "input_length": 6,
                "breakpoints_end_exclusive": [2, 6],
                "segments": [
                    {
                        "length": 2,
                        "source_range": {
                            "start": {"index": 0, "source_row": 10, "timestamp": "2026-05-29 09:00:00", "clock_time": "09:00:00"},
                            "end": {"index": 1, "source_row": 11, "timestamp": "2026-05-29 09:01:00", "clock_time": "09:01:00"},
                        },
                    },
                    {
                        "length": 4,
                        "source_range": {
                            "start": {"index": 2, "source_row": 12, "timestamp": "2026-05-29 09:02:00", "clock_time": "09:02:00"},
                            "end": {"index": 5, "source_row": 15, "timestamp": "2026-05-29 09:05:00", "clock_time": "09:05:00"},
                        },
                    },
                ],
                "status": "EXECUTED",
            },
            {
                "run_id": "s1",
                "tool": "STUMPY_MATRIX_PROFILE",
                "purpose": "MOTIF_DISCORD_SUBSEQUENCE_EVIDENCE",
                "field": "RAW_CLOSE",
                "window": 3,
                "input_length": 6,
                "profile_row_count": 4,
                "profile_rows": [
                    {"subsequence_index": 0, "matrix_profile": {"value": 0.2, "numeric_state": "FINITE"}, "nearest_neighbor_index": 2},
                    {"subsequence_index": 1, "matrix_profile": {"value": 0.4, "numeric_state": "FINITE"}, "nearest_neighbor_index": 3},
                    {"subsequence_index": 2, "matrix_profile": {"value": 0.6, "numeric_state": "FINITE"}, "nearest_neighbor_index": 0},
                    {"subsequence_index": 3, "matrix_profile": {"value": 0.8, "numeric_state": "FINITE"}, "nearest_neighbor_index": 1},
                ],
                "status": "EXECUTED",
            },
        ],
    }


def test_translation_research_opens_before_final_formula():
    result = assess_formula_readiness(_readiness())
    assert result["translation_measurement_allowed"] is True
    assert result["candidate_state_specification_allowed"] is True
    assert result["final_formula_construction_allowed"] is False
    assert "SEMANTIC_CORPUS_NOT_COMPLETE" in result["final_formula_blockers"]
    assert "CURRENT_EXECUTION_FORMULA_GATE_NOT_OPEN" in result["final_formula_blockers"]


def test_final_formula_requires_every_gate():
    result = assess_formula_readiness(
        _readiness(
            semantic_corpus_complete=True,
            cross_ticker_reconciliation_complete=True,
            cross_date_reconciliation_complete=True,
            cross_month_atlas_complete=True,
            current_execution_formula_gate_open=True,
        )
    )
    assert result["final_formula_construction_allowed"] is True
    assert result["status"] == "FINAL_FORMULA_READY"


def test_lane2_translation_is_non_semantic_and_preserves_boundary_time():
    translated = translate_lane2_packet_result(_stage1_result())
    assert translated["interpretation_state"] == "NON_SEMANTIC_STRUCTURAL_MEASUREMENT_ONLY"
    assert translated["threshold_created"] is False
    assert translated["signal_created"] is False
    assert translated["ruptures"][0]["segment_count"] == 2
    assert translated["ruptures"][0]["internal_change_point_count"] == 1
    assert translated["ruptures"][0]["internal_change_point_refs"][0]["clock_time"] == "09:02:00"
    assert translated["stumpy"][0]["finite_matrix_profile_summary"]["median"] == pytest.approx(0.5)
    assert translated["stumpy"][0]["nearest_neighbor_index_distance_summary"]["median"] == pytest.approx(2.0)
    assert len(translated["translation_fingerprint"]) == 64


def test_lane2_translation_rejects_outcome_contamination():
    result = _stage1_result()
    result["independence_assertions"]["outcomes_consumed"] = True
    with pytest.raises(FormulaTranslationContractError, match="LANE2_STAGE1_CONTAMINATION"):
        translate_lane2_packet_result(result)
