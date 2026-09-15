from a1clean.formula_research.telegram_mg_v8_survivor_replay import _formula_matches, _target_hit


def test_formula_matches_union():
    markers = {"PRE_SIDEWAYS_5D", "IGN_VOLUME_WAKE", "IGN_HIGH_ACCEPTANCE"}
    formulas = [
        {"id": "A", "required": ["PRE_SIDEWAYS_5D", "IGN_VOLUME_WAKE"]},
        {"id": "B", "required": ["PRE_SIDEWAYS_5D", "IGN_FLOW_EXPANSION"]},
        {"id": "C", "required": ["IGN_HIGH_ACCEPTANCE"]},
    ]
    assert _formula_matches(markers, formulas) == ["A", "C"]


def test_target_hit_uses_future_only():
    bars = [
        {"timestamp": "2025-01-02T09:00:00", "high": 100.0},
        {"timestamp": "2025-01-02T09:01:00", "high": 101.0},
        {"timestamp": "2025-01-02T09:02:00", "high": 105.0},
    ]
    assert _target_hit(bars, 0, 105.0) == (True, "09:02")
    assert _target_hit(bars, 1, 106.0) == (False, None)
