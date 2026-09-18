from a1clean.formula_research.v32_observation_envelope import classify_phase

def test_v32_phase_classification_uses_source_flags_not_clock():
    assert classify_phase({
        "CLK_PREOPEN_MATCH_FLAG": "1",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "0",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "0",
        "CLK_POSTCLOSE_FLAG": "0",
    }) == "PREOPEN_MATCH"
    assert classify_phase({
        "CLK_PREOPEN_MATCH_FLAG": "0",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "1",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "0",
        "CLK_POSTCLOSE_FLAG": "0",
    }) == "REGULAR_SESSION1"
    assert classify_phase({
        "CLK_PREOPEN_MATCH_FLAG": "0",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "0",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "1",
        "CLK_POSTCLOSE_FLAG": "0",
    }) == "PRECLOSE_MATCH"
    assert classify_phase({
        "CLK_PREOPEN_MATCH_FLAG": "0",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "0",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "0",
        "CLK_POSTCLOSE_FLAG": "1",
    }) == "POSTCLOSE"


def test_v32_envelope_preserves_required_phase_contract_fields():
    from datetime import datetime
    from types import SimpleNamespace

    from a1clean.formula_research.v32_observation_envelope import (
        PHASE_FIELDS,
        packet_to_envelope_bars,
    )

    assert "IDX_CLOCK_RULESET_CODE" in PHASE_FIELDS
    row = {
        "RAW_OPEN": "100",
        "RAW_HIGH": "101",
        "RAW_LOW": "99",
        "RAW_CLOSE": "100",
        "RAW_VOLUME": "10",
        "RAW_AUX2_PHYSICAL": "1000",
        "RAW_OPENINT_PHYSICAL": "200",
        "SYMBOL_IS_INDEX": "0",
        "SYMBOL_CONTINUOUS_QUOTATIONS_FLAG": "1",
        "IDX_CLOCK_RULESET_CODE": "IDX_RULESET_TEST",
        "IDX_REGULAR_CLOCK_SESSION_CODE": "20",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_PREOPEN_MATCH_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "1",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "0",
        "CLK_POSTCLOSE_FLAG": "0",
        "CLK_PREOPEN_NCP_NO_WITHDRAW_FLAG": "0",
        "CLK_PREOPEN_NCP_NO_AMEND_FLAG": "0",
        "CLK_PRECLOSE_NCP_NO_WITHDRAW_FLAG": "0",
        "CLK_PRECLOSE_NCP_NO_AMEND_FLAG": "0",
        "CLK_RANDOM_CLOSING_FLAG": "0",
        "CLK_WATCHLIST_IEP_WINDOW_FLAG": "0",
    }
    packet = SimpleNamespace(
        header=tuple(row.keys()),
        rows=(row,),
        timestamps=(datetime(2024, 12, 2, 9, 0, 0),),
        identity=SimpleNamespace(
            ticker="AALI",
            trading_date="2024-12-02",
            source_row_first=4997,
        ),
    )
    bars = packet_to_envelope_bars(packet, allow_haka_haki=True)
    assert len(bars) == 1
    bar = bars[0]
    assert bar["source_row"] == 4997
    assert bar["source_phase"] == "REGULAR_SESSION1"
    assert bar["observation_role"] == "REGULAR_SESSION1"
    assert bar["idx_clock_ruleset_code"] == "IDX_RULESET_TEST"
    assert bar["idx_regular_clock_session_code"] == 20
    assert bar["regular_behavior_eligible"] is True
    assert bar["phase_flags"]["CLK_REGULAR_SESSION1_FLAG"] is True
    assert bar["haka"] == 600.0
    assert bar["haki"] == 400.0
    assert bar["haka_haki_status"] == "RECONSTRUCTED_PROVEN_SCOPE"


def test_v32_terminal_and_carry_contract_keeps_regular_and_source_terminal_separate():
    import json
    import sqlite3

    from a1clean.formula_research.v32_full_observation_semantic_enrichment import (
        _carry_for_full_observation,
        _init_journey_carry,
        _store_journey_carry,
        _terminal_summary,
    )

    regular = {
        "timestamp": "2024-12-02 15:49:00",
        "source_row": 5098,
        "source_phase": "REGULAR_SESSION2",
        "observation_role": "REGULAR_SESSION2",
        "idx_clock_ruleset_code": "IDX",
        "idx_regular_clock_session_code": 40,
        "phase_flags": {"CLK_REGULAR_SESSION2_FLAG": True},
        "close": 6175,
        "flow_available": True,
        "mechanism_eligible": True,
        "session_eligible": True,
        "regular_behavior_eligible": True,
        "haka_haki_status": "RECONSTRUCTED_PROVEN_SCOPE",
    }
    source_terminal = {
        **regular,
        "timestamp": "2024-12-02 16:01:00",
        "source_row": 5100,
        "source_phase": "PRECLOSE_MATCH",
        "observation_role": "PRECLOSE_MATCH",
        "idx_regular_clock_session_code": 51,
        "close": 6125,
        "flow_available": False,
        "mechanism_eligible": False,
        "session_eligible": False,
        "regular_behavior_eligible": False,
    }
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE calendar(day TEXT PRIMARY KEY, previous_day TEXT)")
    db.executemany(
        "INSERT INTO calendar VALUES(?,?)",
        [("2024-12-02", None), ("2024-12-03", "2024-12-02")],
    )
    db.execute(
        "CREATE TABLE days("
        "source_order INTEGER, source TEXT, source_drive_id TEXT, source_sha256 TEXT, generation_id TEXT, "
        "ticker TEXT, day TEXT, source_observation_count INTEGER, regular_count INTEGER, "
        "first_timestamp TEXT, last_timestamp TEXT, last_regular_state_json TEXT, "
        "last_source_state_json TEXT, closing_match_state_json TEXT, "
        "PRIMARY KEY(source,ticker,day))"
    )
    db.execute(
        "INSERT INTO days VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            0,
            "Raw Des 02-31-2024.csv",
            "drive",
            "sha",
            "gen",
            "AALI",
            "2024-12-02",
            104,
            102,
            "2024-12-02 09:00:00",
            "2024-12-02 16:01:00",
            json.dumps(_terminal_summary(regular)),
            json.dumps(_terminal_summary(source_terminal)),
            json.dumps({"observation_count": 2, "last": _terminal_summary(source_terminal)}),
        ),
    )
    _init_journey_carry(db)
    _store_journey_carry(
        db,
        ticker="AALI",
        day="2024-12-02",
        journeys=[
            {
                "journey_kind": "RECOVERY",
                "causal_start": {"timestamp": "2024-12-02 14:29:00"},
                "hindsight_resolution": {
                    "resolution_status": "OPEN_RIGHT_CENSORED",
                    "right_censored": True,
                },
            }
        ],
    )
    carry, prev = _carry_for_full_observation(db, ticker="AALI", day="2024-12-03")
    assert prev == "2024-12-02"
    assert carry["last_regular_session_state"]["close"] == 6175
    assert carry["last_source_supported_observation_state"]["close"] == 6125
    assert carry["previous_terminal_observation_phase"] == "PRECLOSE_MATCH"
    assert carry["known_at_boundary"] == "2024-12-02 16:01:00"
    assert carry["prior_event_journey_open_right_censored_state"]["open_right_censored_count"] == 1



def test_v32_behavior_lifecycle_materializes_manual_contract_without_hidden_targets():
    from a1clean.formula_research.v32_behavior_lifecycle import (
        LIFECYCLE_TIMING_FIELDS,
        enrich_behavior_lifecycle,
    )

    bars = [
        {"timestamp": "2024-12-02 09:00:00", "source_row": 1, "open": 100, "high": 100, "low": 99, "close": 99, "volume": 10, "trade_value": 990, "nbss": -50, "flow_available": True, "mechanism_eligible": True, "regular_behavior_eligible": True},
        {"timestamp": "2024-12-02 09:01:00", "source_row": 2, "open": 99, "high": 100, "low": 99, "close": 100, "volume": 20, "trade_value": 2000, "nbss": 80, "flow_available": True, "mechanism_eligible": True, "regular_behavior_eligible": True},
        {"timestamp": "2024-12-02 09:02:00", "source_row": 3, "open": 100, "high": 102, "low": 100, "close": 102, "volume": 30, "trade_value": 3060, "nbss": 100, "flow_available": True, "mechanism_eligible": True, "regular_behavior_eligible": True},
        {"timestamp": "2024-12-02 09:03:00", "source_row": 4, "open": 102, "high": 102, "low": 100, "close": 100, "volume": 15, "trade_value": 1500, "nbss": -20, "flow_available": True, "mechanism_eligible": True, "regular_behavior_eligible": True},
    ]
    runs = [
        {"start_index": 0, "end_index": 0, "start_timestamp": bars[0]["timestamp"], "end_timestamp": bars[0]["timestamp"], "row_count": 1, "state_key": "A", "state": {"price_direction": "DOWN"}, "start_close": 99, "end_close": 99},
        {"start_index": 1, "end_index": 2, "start_timestamp": bars[1]["timestamp"], "end_timestamp": bars[2]["timestamp"], "row_count": 2, "state_key": "B", "state": {"price_direction": "UP"}, "start_close": 100, "end_close": 102},
        {"start_index": 3, "end_index": 3, "start_timestamp": bars[3]["timestamp"], "end_timestamp": bars[3]["timestamp"], "row_count": 1, "state_key": "C", "state": {"price_direction": "DOWN"}, "start_close": 100, "end_close": 100},
    ]
    journeys = [{
        "journey_kind": "RECOVERY",
        "causal_start": {"index": 1, "timestamp": bars[1]["timestamp"], "close": 100, "known_at": bars[1]["timestamp"]},
        "hindsight_resolution": {"resolution_status": "FAILED_BELOW_RECOVERY_START_CLOSE", "resolution_index": 3, "resolution_timestamp": bars[3]["timestamp"], "right_censored": False},
        "future_resolution_not_used_to_define_start": True,
    }]
    profile, lifecycle, path = enrich_behavior_lifecycle(
        bars=bars,
        full_envelope=bars,
        runs=runs,
        journeys=journeys,
        source="Raw Des 02-31-2024.csv",
        ticker="TEST",
        trading_date="2024-12-02",
        carry_in=None,
    )
    assert len(lifecycle) == 1
    rec = lifecycle[0]
    assert rec["manual_label_used_as_target"] is False
    assert rec["arbitrary_threshold_added"] is False
    assert rec["timing_contract_complete"] is True
    assert tuple(rec["timing_contract_fields"]) == LIFECYCLE_TIMING_FIELDS
    assert rec["timing"]["event_start_time"].endswith("09:01:00")
    assert rec["timing"]["first_detectable_time"].endswith("09:01:00")
    assert rec["timing"]["confirm_time"].endswith("09:02:00")
    assert rec["timing"]["peak_time"].endswith("09:02:00")
    assert rec["timing"]["weakening_time"].endswith("09:03:00")
    assert rec["timing"]["fail_time"].endswith("09:03:00")
    assert rec["timing"]["event_end_time"].endswith("09:03:00")
    assert rec["formation_sequence"][0]["role"] == "PRIOR_CONDITION_RUN"
    assert profile["lifecycle_contract"]["formation_sequence"] is True
    assert profile["no_forced_event"] is False
    assert path["formation_run_count"] == 3
    assert path["state_transition_count"] == 2
    assert path["all_machine_state_changes_preserved_even_without_event_label"] is True


def test_v32_behavior_lifecycle_preserves_open_and_no_event_states():
    from a1clean.formula_research.v32_behavior_lifecycle import enrich_behavior_lifecycle

    bars = [
        {"timestamp": "2024-12-02 09:00:00", "source_row": 1, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 10, "trade_value": 1000, "flow_available": False, "mechanism_eligible": False, "regular_behavior_eligible": True},
        {"timestamp": "2024-12-02 09:01:00", "source_row": 2, "open": 100, "high": 101, "low": 100, "close": 101, "volume": 10, "trade_value": 1010, "flow_available": False, "mechanism_eligible": False, "regular_behavior_eligible": True},
    ]
    profile0, rec0, path0 = enrich_behavior_lifecycle(
        bars=bars,
        full_envelope=bars,
        runs=[],
        journeys=[],
        source="S",
        ticker="NOEV",
        trading_date="2024-12-02",
        carry_in=None,
    )
    assert rec0 == []
    assert profile0["no_forced_event"] is True
    assert profile0["observation_only_day_preserved"] is True
    assert path0["no_forced_event"] is True

    journey = {
        "journey_kind": "RECOVERY",
        "causal_start": {"index": 1, "timestamp": bars[1]["timestamp"]},
        "hindsight_resolution": {"resolution_status": "OPEN_RIGHT_CENSORED", "resolution_timestamp": None, "right_censored": True},
    }
    profile1, rec1, path1 = enrich_behavior_lifecycle(
        bars=bars,
        full_envelope=bars,
        runs=[{"start_index": 0, "end_index": 0, "start_timestamp": bars[0]["timestamp"], "end_timestamp": bars[0]["timestamp"], "row_count": 1, "state_key": "A", "state": {}, "start_close": 100, "end_close": 100}, {"start_index": 1, "end_index": 1, "start_timestamp": bars[1]["timestamp"], "end_timestamp": bars[1]["timestamp"], "row_count": 1, "state_key": "B", "state": {}, "start_close": 101, "end_close": 101}],
        journeys=[journey],
        source="S",
        ticker="OPEN",
        trading_date="2024-12-02",
        carry_in=None,
    )
    assert rec1[0]["timing"]["event_end_time"] == "OPEN"
    assert rec1[0]["right_censored_open"] is True
    assert profile1["open_right_censored_journey_count"] == 1
    assert path1["lifecycle_journey_count"] == 1


def test_v32_source_regular_phase_does_not_force_legacy_behavior_eligibility():
    from datetime import datetime
    from types import SimpleNamespace

    from a1clean.formula_research.v32_observation_envelope import packet_to_envelope_bars

    row = {
        "RAW_OPEN": "100",
        "RAW_HIGH": "100",
        "RAW_LOW": "100",
        "RAW_CLOSE": "100",
        "RAW_VOLUME": "1",
        "RAW_AUX2_PHYSICAL": "100",
        "RAW_OPENINT_PHYSICAL": "0",
        "SYMBOL_IS_INDEX": "0",
        "SYMBOL_CONTINUOUS_QUOTATIONS_FLAG": "0",
        "IDX_CLOCK_RULESET_CODE": "IDX_RULESET_TEST",
        "IDX_REGULAR_CLOCK_SESSION_CODE": "20",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_PREOPEN_MATCH_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "1",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "0",
        "CLK_POSTCLOSE_FLAG": "0",
        "CLK_PREOPEN_NCP_NO_WITHDRAW_FLAG": "0",
        "CLK_PREOPEN_NCP_NO_AMEND_FLAG": "0",
        "CLK_PRECLOSE_NCP_NO_WITHDRAW_FLAG": "0",
        "CLK_PRECLOSE_NCP_NO_AMEND_FLAG": "0",
        "CLK_RANDOM_CLOSING_FLAG": "0",
        "CLK_WATCHLIST_IEP_WINDOW_FLAG": "0",
    }
    packet = SimpleNamespace(
        header=tuple(row.keys()),
        rows=(row,),
        timestamps=(datetime(2024, 12, 2, 9, 0, 0),),
        identity=SimpleNamespace(
            ticker="BISNIS-27",
            trading_date="2024-12-02",
            source_row_first=1,
        ),
    )
    bar = packet_to_envelope_bars(packet)[0]
    assert bar["source_phase"] == "REGULAR_SESSION1"
    assert bar["source_regular_phase"] is True
    assert bar["legacy_formula_session_eligible"] is False
    assert bar["regular_behavior_eligible"] is False
    assert bar["nonregular_context_observation"] is True
    assert bar["phase_behavior_eligibility_relation"] == "SOURCE_REGULAR_BUT_BEHAVIOR_INELIGIBLE"
    assert bar["behavior_exclusion_reason"] == "LEGACY_FORMULA_SYMBOL_OR_SESSION_ELIGIBILITY_FALSE"


def test_v32_retains_unknown_source_fields_for_reverse_trace():
    from datetime import datetime
    from types import SimpleNamespace

    from a1clean.formula_research.v32_observation_envelope import packet_to_envelope_bars

    row = {
        "RAW_OPEN": "100",
        "RAW_HIGH": "101",
        "RAW_LOW": "99",
        "RAW_CLOSE": "100",
        "RAW_VOLUME": "10",
        "RAW_AUX2_PHYSICAL": "1000",
        "RAW_OPENINT_PHYSICAL": "5",
        "SYMBOL_IS_INDEX": "0",
        "SYMBOL_CONTINUOUS_QUOTATIONS_FLAG": "1",
        "IDX_CLOCK_RULESET_CODE": "IDX_RULESET_TEST",
        "IDX_REGULAR_CLOCK_SESSION_CODE": "20",
        "CLK_PREOPEN_INPUT_FLAG": "0",
        "CLK_PREOPEN_MATCH_FLAG": "0",
        "CLK_REGULAR_SESSION1_FLAG": "1",
        "CLK_OFFICIAL_MIDDAY_BREAK_FLAG": "0",
        "CLK_REGULAR_SESSION2_FLAG": "0",
        "CLK_PRECLOSE_INPUT_FLAG": "0",
        "CLK_PRECLOSE_MATCH_FLAG": "0",
        "CLK_POSTCLOSE_FLAG": "0",
        "CLK_PREOPEN_NCP_NO_WITHDRAW_FLAG": "0",
        "CLK_PREOPEN_NCP_NO_AMEND_FLAG": "0",
        "CLK_PRECLOSE_NCP_NO_WITHDRAW_FLAG": "0",
        "CLK_PRECLOSE_NCP_NO_AMEND_FLAG": "0",
        "CLK_RANDOM_CLOSING_FLAG": "0",
        "CLK_WATCHLIST_IEP_WINDOW_FLAG": "0",
        "FUTURE_PROVIDER_FIELD_X": "opaque-value",
    }
    header = tuple(row.keys())
    packet = SimpleNamespace(
        header=header,
        rows=(row,),
        timestamps=(datetime(2024, 12, 2, 9, 0, 0),),
        packet_fingerprint="packet-fingerprint-test",
        identity=SimpleNamespace(
            ticker="TEST",
            trading_date="2024-12-02",
            source_row_first=10,
        ),
    )
    bar = packet_to_envelope_bars(packet)[0]
    assert bar["source_field_count"] == len(header)
    assert bar["source_field_values"] == [row[field] for field in header]
    assert bar["source_packet_fingerprint"] == "packet-fingerprint-test"
    idx = header.index("FUTURE_PROVIDER_FIELD_X")
    assert bar["source_field_values"][idx] == "opaque-value"
