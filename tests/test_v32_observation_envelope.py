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
