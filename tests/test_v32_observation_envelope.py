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
