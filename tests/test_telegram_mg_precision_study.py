from a1clean.formula_research.telegram_mg_precision_study import (
    PRECISION_VARIANTS,
    _candidate_features,
    _same_day_outcome,
    _variant_matches,
)


def _bar(i, close, *, s1=True, s2=False, high=None, low=None):
    return {
        "close": float(close),
        "high": float(high if high is not None else close + 0.25),
        "low": float(low if low is not None else close - 0.25),
        "regular_session1": s1,
        "regular_session2": s2,
        "timestamp": f"2024-12-03 09:{i:02d}:00",
    }


def test_session_safe_features_require_dependency_window_inside_one_session():
    bars = [_bar(i, 100 + i * 0.2) for i in range(6)]
    features = _candidate_features(bars, 5, lookback=5)
    assert features["session_safe"] is True
    assert features["session_segment"] == "S1"
    assert features["recent_return_pct"] is not None
    assert features["local_range_step_pct"] is not None

    bars[0]["regular_session1"] = False
    bars[0]["regular_session2"] = True
    crossed = _candidate_features(bars, 5, lookback=5)
    assert crossed["session_safe"] is False


def test_tight_precision_variant_requires_small_step_and_constructive_not_mature_return():
    rule = PRECISION_VARIANTS["MG_P1_STEP075_RET025_200"]
    assert _variant_matches(
        {"session_safe": True, "local_range_step_pct": 0.70, "recent_return_pct": 1.10},
        rule,
    )
    assert not _variant_matches(
        {"session_safe": True, "local_range_step_pct": 0.90, "recent_return_pct": 1.10},
        rule,
    )
    assert not _variant_matches(
        {"session_safe": True, "local_range_step_pct": 0.70, "recent_return_pct": 2.50},
        rule,
    )
    assert not _variant_matches(
        {"session_safe": False, "local_range_step_pct": 0.50, "recent_return_pct": 1.00},
        rule,
    )


def test_same_day_outcome_does_not_count_alert_bar_high():
    bars = [
        _bar(0, 100.0, high=105.0, low=99.0),
        _bar(1, 100.5, high=101.0, low=99.5),
        _bar(2, 100.0, high=100.5, low=99.0),
    ]
    outcome = _same_day_outcome(bars, 0, entry=100.0, tp1=102.0, tp2=104.0)
    assert outcome["evaluable"] is True
    assert outcome["tp1_hit"] is False
    assert outcome["tp2_hit"] is False
    assert outcome["result"] == "NO_TP"
