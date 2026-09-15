from a1clean.formula_research import telegram_mg_multihypothesis_v8 as v8
from a1clean.formula_research.telegram_mg_multihypothesis_v8f import _outcome_fast


def _bars():
    out = []
    for i in range(40):
        base = 100.0 + (i % 7) * 0.5 + i * 0.07
        out.append({
            "open": base,
            "high": base + 1.0 + (i % 3) * 0.1,
            "low": base - 0.8 - (i % 4) * 0.05,
            "close": base + 0.2,
        })
    return out


def test_outcome_fast_matches_original():
    bars = _bars()
    for index in (5, 10, 15, 20, 25, 30):
        expected = v8._outcome(bars, index, 0.15, 0.25)
        actual = _outcome_fast(bars, index, 0.15, 0.25)
        assert set(actual) == set(expected)
        for key, value in expected.items():
            if isinstance(value, float):
                assert abs(float(actual[key]) - value) < 1e-12
            else:
                assert actual[key] == value
