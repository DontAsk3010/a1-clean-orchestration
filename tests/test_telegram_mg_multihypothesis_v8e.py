from a1clean.formula_research import telegram_mg_multihypothesis_v8 as v8
from a1clean.formula_research.telegram_mg_multihypothesis_v8e import _prefix_series


def _bars():
    out = []
    for i in range(12):
        px = 100.0 + i
        out.append({
            "open": px - 0.5,
            "high": px + 1.0,
            "low": px - 1.0,
            "close": px,
            "volume": 1000.0 + 10.0 * i,
            "trade_value": 100000.0 + 1000.0 * i,
            "nbss": 1000.0 if i % 3 else 0.0,
        })
    return out


def test_prefix_series_matches_original_prefix_stats():
    bars = _bars()
    cached = _prefix_series(bars)
    assert len(cached) == len(bars)
    for i in range(len(bars)):
        expected = v8._prefix_stats(bars, i)
        actual = cached[i]
        assert set(actual) == set(expected)
        for key, value in expected.items():
            if value is None:
                assert actual[key] is None
            else:
                assert abs(float(actual[key]) - float(value)) < 1e-12
