from a1clean.formula_research import telegram_mg_multihypothesis_v8 as v8
from a1clean.formula_research.telegram_mg_multihypothesis_v8e import _event_features_fast, _prefix_series


def _day(day: int, shift: float):
    bars = []
    for i in range(20):
        px = 100.0 + shift + i * 0.1
        bars.append({
            "open": px,
            "high": px + 0.8,
            "low": px - 0.7,
            "close": px + 0.2,
            "volume": 1000.0 + day * 20 + i,
            "trade_value": 100000.0 + day * 1000 + i * 100,
            "nbss": 500.0 + day * 10 if i % 2 else 0.0,
        })
    return bars


def test_event_features_fast_matches_original():
    history_bars = [_day(1, 0.0), _day(2, 1.0), _day(3, -0.5)]
    history_daily = [v8._daily(b, f"2025-01-0{i+1}") for i, b in enumerate(history_bars)]
    history_daily = [d for d in history_daily if d is not None]
    history_prefix = [_prefix_series(b) for b in history_bars]
    current = _day(4, 0.7)
    current_prefix = _prefix_series(current)
    for index in (4, 9, 14, 19):
        expected = v8._event_features(current, index, history_daily, history_bars)
        actual = _event_features_fast(current, index, history_daily, history_prefix, current_prefix)
        assert set(actual) == set(expected)
        for key, value in expected.items():
            if value is None:
                assert actual[key] is None
            else:
                assert abs(float(actual[key]) - float(value)) < 1e-12
