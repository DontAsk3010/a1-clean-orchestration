import json

from a1clean.formula_research.v32_behavior_grouping_atlas import (
    FORMULA_STAGE,
    STATUS,
    _day_axes,
    _lifecycle_axes,
    _signature,
)


def test_group_signature_is_exact_and_deterministic():
    left = {"b": [2, 3], "a": 1}
    right = {"a": 1, "b": [2, 3]}
    gid1, sig1 = _signature("TEST_AXIS", left)
    gid2, sig2 = _signature("TEST_AXIS", right)
    assert gid1 == gid2
    assert sig1 == sig2
    assert json.loads(sig1) == right


def test_day_axes_preserve_multi_lane_paths_without_thresholds():
    path = {
        "formation_run_path": [
            {
                "state_key": "S1",
                "state": {
                    "price_direction": "FLAT",
                    "volume_direction": "UP",
                    "value_direction": "UP",
                    "flow_direction": "BUY",
                    "flow_effort_change": "ACCEL",
                    "value_activity_change": "ACCEL",
                    "bar_range_change": "FLAT",
                    "flow_price_relation": "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE",
                    "fresh_high": False,
                    "fresh_low": False,
                    "open_state": "DEFENDED_NOT_YET_BROKEN",
                    "haka_haki_dominance": "HAKA",
                },
            },
            {
                "state_key": "S2",
                "state": {
                    "price_direction": "UP",
                    "volume_direction": "UP",
                    "value_direction": "UP",
                    "flow_direction": "BUY",
                    "flow_effort_change": "ACCEL",
                    "value_activity_change": "ACCEL",
                    "bar_range_change": "UP",
                    "flow_price_relation": "BUY_FLOW_PRICE_ADVANCE",
                    "fresh_high": True,
                    "fresh_low": False,
                    "open_state": "DEFENDED_NOT_YET_BROKEN",
                    "haka_haki_dominance": "HAKA",
                },
            },
        ],
        "state_transitions": [
            {"changed_dimensions": {"price_direction": {}, "flow_price_relation": {}, "fresh_high": {}}}
        ],
        "lifecycle_journey_refs": [
            {"journey_kind": "RECOVERY", "right_censored_open": False}
        ],
        "no_forced_event": False,
        "prior_condition_carry": {"previous_day": "2024-12-01"},
        "last_source_supported_observation": {"source_phase": "PRECLOSE_MATCH"},
    }
    td = {
        "availability": {
            "participant_broker_flow": "UNKNOWN_UNPROVEN",
            "haka_haki": "SOURCE_BOUND_PROVEN",
        },
        "source_phase_counts": {"REGULAR_SESSION1": 2, "PRECLOSE_MATCH": 1},
    }
    axes = _day_axes(path, td)
    assert axes["FULL_STATE_SEQUENCE"] == ["S1", "S2"]
    assert axes["PRICE_PATH"] == ["FLAT", "UP"]
    assert axes["FLOW_DIRECTION_PATH"] == ["BUY"]
    assert axes["FLOW_PRICE_RESPONSE_PATH"] == [
        "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE",
        "BUY_FLOW_PRICE_ADVANCE",
    ]
    assert axes["HAKA_HAKI_PATH"] == ["HAKA"]
    assert axes["TRANSITION_DIMENSION_PATH"] == [["flow_price_relation", "fresh_high", "price_direction"]]
    assert axes["EVIDENCE_AVAILABILITY"]["participant_broker_flow"] == "UNKNOWN_UNPROVEN"
    assert axes["CROSS_DATE_CARRY_PRESENT"] is True
    assert axes["SOURCE_TERMINAL_PHASE"] == "PRECLOSE_MATCH"


def test_lifecycle_grouping_keeps_causal_formation_separate_from_hindsight_outcome():
    rec = {
        "journey_kind": "RECOVERY",
        "directional_role": "UP",
        "journey_id": "J1",
        "formation_sequence": [
            {"role": "PRIOR_CONDITION_RUN", "state_key": "A"},
            {"role": "EVENT_FORMATION_RUN", "state_key": "B"},
        ],
        "timing": {"event_start_time": "2025-01-02 09:03:00"},
        "right_censored_open": False,
        "hindsight_resolution": {"resolution_status": "FAILED_BELOW_RECOVERY_START_CLOSE"},
    }
    axes, formation_id, formation_sig, resolution = _lifecycle_axes(rec)
    assert axes["JOURNEY_KIND"] == "RECOVERY"
    assert axes["JOURNEY_EVENT_START_CLOCK"] == "09:03:00"
    assert axes["JOURNEY_FORMATION_SEQUENCE"] == [
        {"role": "PRIOR_CONDITION_RUN", "state_key": "A"},
        {"role": "EVENT_FORMATION_RUN", "state_key": "B"},
    ]
    assert resolution == "FAILED_BELOW_RECOVERY_START_CLOSE"
    assert "FAILED" not in formation_sig
    assert formation_id == _signature("JOURNEY_FORMATION_SEQUENCE", axes["JOURNEY_FORMATION_SEQUENCE"])[0]
    assert STATUS == "PROVISIONAL_BEHAVIOR_ATLAS"
    assert FORMULA_STAGE == "CLOSED"
