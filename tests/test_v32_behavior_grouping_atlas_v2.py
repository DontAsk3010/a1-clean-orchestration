import json

from a1clean.formula_research.v32_behavior_grouping_atlas import _signature
from a1clean.formula_research.v32_behavior_grouping_atlas_v2 import (
    AXIS_VERSION,
    FORMULA_STAGE,
    REQUIRED_CURRENT_STAGE_AXES,
    SCHEMA,
    STATUS,
    _day_axes,
    _hindsight_axes,
    _lifecycle_axes,
)


def _path():
    return {
        "formation_run_path": [
            {
                "state_key": "S1", "start_index": 0, "end_index": 1,
                "start_timestamp": "2025-01-02T09:00:00", "end_timestamp": "2025-01-02T09:01:00", "row_count": 2,
                "state": {"price_direction":"FLAT","volume_direction":"UP","value_direction":"UP","flow_direction":"BUY",
                          "flow_effort_change":"ACCEL","value_activity_change":"ACCEL","bar_range_change":"FLAT",
                          "flow_price_relation":"BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE","fresh_high":False,"fresh_low":False,
                          "open_state":"DEFENDED_NOT_YET_BROKEN","haka_haki_dominance":"HAKA"},
            },
            {
                "state_key": "S2", "start_index": 2, "end_index": 2,
                "start_timestamp": "2025-01-02T09:02:00", "end_timestamp": "2025-01-02T09:02:00", "row_count": 1,
                "state": {"price_direction":"UP","volume_direction":"UP","value_direction":"UP","flow_direction":"BUY",
                          "flow_effort_change":"DECEL","value_activity_change":"ACCEL","bar_range_change":"UP",
                          "flow_price_relation":"BUY_FLOW_PRICE_ADVANCE","fresh_high":True,"fresh_low":False,
                          "open_state":"DEFENDED_NOT_YET_BROKEN","haka_haki_dominance":"HAKA"},
            },
            {
                "state_key": "S1", "start_index": 3, "end_index": 3,
                "start_timestamp": "2025-01-02T09:03:00", "end_timestamp": "2025-01-02T09:03:00", "row_count": 1,
                "state": {"price_direction":"FLAT","volume_direction":"DOWN","value_direction":"DOWN","flow_direction":"BUY",
                          "flow_effort_change":"DECEL","value_activity_change":"DECEL","bar_range_change":"DOWN",
                          "flow_price_relation":"BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE","fresh_high":False,"fresh_low":False,
                          "open_state":"DEFENDED_NOT_YET_BROKEN","haka_haki_dominance":"HAKA"},
            },
        ],
        "state_transitions": [
            {"transition_ordinal":1,"known_at_time":"2025-01-02T09:02:00","from_state_key":"S1","to_state_key":"S2",
             "changed_dimensions":{"price_direction":{},"flow_price_relation":{}}},
            {"transition_ordinal":2,"known_at_time":"2025-01-02T09:03:00","from_state_key":"S2","to_state_key":"S1",
             "changed_dimensions":{"price_direction":{},"flow_price_relation":{}}},
        ],
        "lifecycle_journey_refs": [{"journey_kind":"RECOVERY","event_start_time":"2025-01-02T09:02:00","right_censored_open":False}],
        "no_forced_event": False,
        "prior_condition_carry": {"status":"EXACT_PREVIOUS_GOVERNED_DATE_SOURCE_SUPPORTED_CARRY","previous_governed_date":"2025-01-01",
                                  "known_at_boundary":"2025-01-01T15:59:00","previous_terminal_observation_phase":"PRECLOSE_MATCH"},
        "first_regular_observation": {"timestamp":"2025-01-02T09:00:00"},
        "last_regular_observation": {"timestamp":"2025-01-02T09:03:00"},
        "last_source_supported_observation": {"timestamp":"2025-01-02T16:00:00","source_phase":"PRECLOSE_MATCH"},
    }


def _td():
    return {"availability":{"participant_broker_flow":"UNKNOWN_UNPROVEN","haka_haki":"SOURCE_BOUND_PROVEN"},
            "source_phase_counts":{"REGULAR_SESSION1":4,"PRECLOSE_MATCH":1},
            "source_observation_count":5,"regular_bar_count":4,"nonregular_context_observation_count":1}


def _regular():
    bars=[]
    for ts,op,hi,lo,cl in [
        ("09:00:00",100,101,99,100),("09:01:00",100,101,100,100),
        ("09:02:00",100,102,100,102),("09:03:00",102,102,101,102)]:
        bars.append({"timestamp":f"2025-01-02T{ts}","source_phase":"REGULAR_SESSION1","idx_regular_clock_session_code":"S1",
                     "observation_role":"REGULAR","open":op,"high":hi,"low":lo,"close":cl})
    return {"source":"Raw Des 02-31-2024.csv","ticker":"AAA","date":"2025-01-02","bars":bars}


def test_v2_day_axes_add_exact_temporal_and_blindspot_contract():
    axes=_day_axes(_path(),_td(),_regular())
    assert axes["STATE_ORDER"] == ["S1","S2","S1"]
    assert axes["STATE_RUN_TIMING_PROFILE"][0]["source_clock_elapsed_seconds"] == 60
    assert axes["SESSION_PHASE"][1]["start_phase"]["source_phase"] == "REGULAR_SESSION1"
    assert axes["STATE_REAPPEARANCE_PROFILE"][0]["occurrence_ordinals"] == [1,3]
    assert axes["NEGATIVE_EVIDENCE_PATH"][0]["relation"] == "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE"
    assert ["EQUAL_RUNNING_HIGH_RETEST","ABOVE_RUNNING_LOW"] in axes["FRESH_EXTREME_ATTEMPT_PROFILE"]
    assert axes["CROSS_DATE_TEMPORAL_CARRY"]["present"] is True
    assert set(axes).issubset(set(REQUIRED_CURRENT_STAGE_AXES))


def test_v2_exact_causal_formation_changes_when_timing_changes_and_hindsight_stays_separate():
    rec={
        "journey_kind":"RECOVERY","directional_role":"UP","right_censored_open":False,
        "formation_sequence":[
            {"role":"PRIOR_CONDITION_RUN","state_key":"A","start_timestamp":"2025-01-02T09:00:00","end_timestamp":"2025-01-02T09:01:00","row_count":2,"start_index":0,"end_index":1},
            {"role":"EVENT_FORMATION_RUN","state_key":"B","start_timestamp":"2025-01-02T09:02:00","end_timestamp":"2025-01-02T09:04:00","row_count":3,"start_index":2,"end_index":4},
        ],
        "timing":{"first_observed_time":"2025-01-02T09:02:00","event_start_time":"2025-01-02T09:02:00",
                  "first_detectable_time":"2025-01-02T09:02:00","change_point_time":"2025-01-02T09:02:00","known_at_time":"2025-01-02T09:02:00",
                  "confirm_time":"2025-01-02T09:03:00","extreme_time":"2025-01-02T09:04:00","last_observed_time":"2025-01-02T09:05:00","event_end_time":"2025-01-02T09:05:00"},
        "critical_evidence":{"event_start":{"source_phase":"REGULAR_SESSION1"}},"timestamp_discontinuities":[],
        "temporal_connected_chain":{"chain_id":"C1","member_count":1,"member_ordinals":[1],"semantic_merge_asserted":False},
        "prior_condition":{"regular_prior_bar":{"timestamp":"2025-01-02T09:01:00"}},
        "hindsight_resolution":{"resolution_status":"RECOVERY_EXTENDED_TO_NEW_PRESTART_RUNNING_HIGH","resolution_timestamp":"2025-01-02T09:05:00","right_censored":False},
    }
    axes,fid,fsig,res=_lifecycle_axes(rec)
    assert axes["JOURNEY_START_SOURCE_PHASE"] == "REGULAR_SESSION1"
    assert axes["JOURNEY_RESPONSE_LAG_PROFILE"]["start_to_confirm_seconds"] == 60
    assert res not in fsig
    hindsight=_hindsight_axes(rec,fid,res)
    assert hindsight["HINDSIGHT_RESOLUTION_TIMING_PROFILE"]["start_to_resolution_seconds"] == 180
    shifted=json.loads(json.dumps(rec)); shifted["timing"]["event_start_time"]="2025-01-02T11:02:00"; shifted["formation_sequence"][1]["start_timestamp"]="2025-01-02T11:02:00"
    assert _lifecycle_axes(shifted)[1] != fid
    assert SCHEMA == "A1_V32_BEHAVIOR_GROUPING_ATLAS_V2"
    assert AXIS_VERSION == "M2_MULTI_AXIS_EXACT_SIGNATURE_TEMPORAL_BLINDSPOT_V2"
    assert STATUS == "PROVISIONAL_BEHAVIOR_ATLAS" and FORMULA_STAGE == "CLOSED"


def test_signature_stays_deterministic():
    assert _signature("X",{"b":2,"a":1}) == _signature("X",{"a":1,"b":2})
