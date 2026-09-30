from __future__ import annotations

import pytest

from a1clean.formula_research.machine2_current_store import (
    MACHINE2_CHECKPOINT_FOLDER_ID,
    MACHINE2_CURRENT_STATE_FOLDER_ID,
    MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
)
from a1clean.formula_research.m2_current_execution_contract import (
    SAFE_ATOMIC_UNITS_PER_SHARD,
    assert_safe_atomic_units_per_shard,
    validate_checkpoint_exact_resume,
    validate_request_for_current_atomic_restart,
)
from a1clean.formula_research.v32_current_scientific_restart import (
    CHECKPOINT_NAME,
    LINEAGE,
    build_continuous_current_enrichment,
)


def _bar(i: int, *, close: float, volume: float, value: float, nbss: float, high: float, low: float) -> dict:
    return {
        "source_row": 100 + i,
        "timestamp": f"2024-12-02 09:{i:02d}:00",
        "source_phase": "REGULAR_SESSION1",
        "regular_behavior_eligible": True,
        "open": close - 1.0,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "trade_value": value,
        "nbss": nbss,
        "haka": value + nbss,
        "haki": value - nbss,
        "haka_haki_status": "SOURCE_BOUND_PROVEN",
        "source_field_count": 12,
        "source_packet_fingerprint": "packet-fp",
    }


def _exact_ref(position: int) -> dict:
    return {
        "selection_position": position,
        "manifest_index": position + 10,
        "trading_date": "2024-12-02",
        "ticker": "AALI",
        "data_row_count": 300,
        "first_clock_time": "09:00:00",
        "last_clock_time": "15:49:00",
        "source_row_first": 1000 + position * 300,
        "source_row_last": 1299 + position * 300,
    }


def _open_request() -> dict:
    return {
        "enabled": True,
        "restart_authorized": True,
        "machine2_full_scientific_restart_from_beginning_required": True,
        "old_pass_may_skip_current_reading_unit": False,
        "old_derived_semantic_checkpoint_completion_inherited": False,
        "date_ticker_record_timestamp_exact_resume_checkpoint_required": True,
        "per_source_only_checkpoint_is_not_sufficient_for_exact_resume": True,
        "strict_governed_chronological_restart_required": True,
        "progressive_current_checkpoint_lineage_must_start_new": True,
        "formula_stage": "CLOSED",
        "grouping_stage": "CLOSED_UNTIL_SEPARATELY_ADMITTED",
    }


def test_current_restart_has_new_lineage_and_canonical_machine2_home():
    assert LINEAGE == "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V1"
    assert "CURRENT_FULL_RESTART" in CHECKPOINT_NAME
    assert MACHINE2_CHECKPOINT_FOLDER_ID == "15L4xQfPxNaulE-uiaGXVYwDdY-2-pBt5"
    assert MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID == "1oHmkK-D-k7aBZn2nK-7KzMS2tujlvzj5"
    assert MACHINE2_CURRENT_STATE_FOLDER_ID == "1UGEgtftUAasKWF0OHdbDGgYErF60m4zB"


def test_current_atomic_execution_contract_requires_one_unit_per_shard():
    assert SAFE_ATOMIC_UNITS_PER_SHARD == 1
    assert_safe_atomic_units_per_shard(1)
    with pytest.raises(RuntimeError, match="M2_CURRENT_SAFE_ATOMIC_CHECKPOINT_REQUIRES_UNITS_PER_SHARD_1"):
        assert_safe_atomic_units_per_shard(20)


def test_current_atomic_execution_contract_rejects_disabled_request():
    request = _open_request()
    validate_request_for_current_atomic_restart(request)
    request["enabled"] = False
    with pytest.raises(RuntimeError, match="M2_CURRENT_HEAVY_RESTART_NOT_AUTHORIZED"):
        validate_request_for_current_atomic_restart(request)


def test_exact_resume_checkpoint_requires_contiguous_full_unit_identity():
    checkpoint = {
        "status": "IN_PROGRESS",
        "completed_units_in_current_date": 1,
        "last_completed": _exact_ref(0),
        "next_exact_resume_point": _exact_ref(1),
    }
    validate_checkpoint_exact_resume(checkpoint)
    checkpoint["next_exact_resume_point"] = _exact_ref(2)
    with pytest.raises(RuntimeError, match="M2_CURRENT_RESUME_POSITION_NOT_CONTIGUOUS"):
        validate_checkpoint_exact_resume(checkpoint)


def test_continuous_enrichment_preserves_path_effort_response_attempts_and_known_at_uncertainty():
    bars = [
        _bar(0, close=100, volume=10, value=1000, nbss=100, high=101, low=98),
        _bar(1, close=102, volume=20, value=2200, nbss=200, high=103, low=99),
        _bar(2, close=102, volume=30, value=3300, nbss=300, high=104, low=101),
    ]
    result = build_continuous_current_enrichment(bars)
    assert result["derived_observation_count"] == 3
    last = result["derived_observations"][-1]
    assert last["price_geometry"]["fresh_high"] is True
    assert last["price_geometry"]["fresh_high_attempt_number"] == 3
    assert last["price_geometry"]["cumulative_close_path_length"] == 2.0
    assert last["activity_flow"]["volume_delta"] == 10.0
    assert last["activity_flow"]["nbss_delta"] == 100.0
    assert "FLOW_PRESENT_PRICE_NO_RESPONSE_THIS_OBSERVATION" in last["effort_response"]["negative_evidence"]
    assert last["causal_timing"]["known_at"] is None
    assert last["causal_timing"]["known_at_status"] == "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS"
    assert last["multi_timescale_descendants"]["3_actual_bars"]["status"] == "AVAILABLE"
    assert last["multi_timescale_descendants"]["5_actual_bars"]["status"] == "INSUFFICIENT_PRIOR_ACTUAL_BARS"


def test_current_restart_does_not_turn_missing_or_unproven_timing_into_zero():
    bars = [_bar(0, close=100, volume=0, value=0, nbss=0, high=100, low=100)]
    result = build_continuous_current_enrichment(bars)
    row = result["derived_observations"][0]
    assert row["causal_timing"]["known_at"] is None
    assert row["causal_timing"]["formation_eligible_at"] is None
    assert row["effort_response"]["nbss_to_price_absolute_efficiency"] is None
    assert row["price_geometry"]["path_efficiency"] is None
