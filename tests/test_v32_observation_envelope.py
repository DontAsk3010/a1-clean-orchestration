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
