from a1clean.formula_research.comparable_context_cache import build_history_context_series
from a1clean.formula_research.telegram_mg_multiday_context_study import DayRecord, _history_context


def _bars(date: str, closes, values):
    out = []
    for i, (c, v) in enumerate(zip(closes, values, strict=True)):
        out.append({
            "trading_date": date,
            "open": c,
            "high": c + 1,
            "low": c - 1,
            "close": c,
            "trade_value": v,
            "regular_session1": True,
            "regular_session2": False,
            "session_eligible": True,
        })
    return out


def test_cached_context_matches_repeated_reference_calls():
    current = _bars("2025-01-03", [100, 101, 102, 103], [10, 20, 30, 40])
    h1 = _bars("2025-01-02", [100, 100, 101, 101], [8, 12, 16, 20])
    h2 = _bars("2024-12-30", [100, 99, 100, 100], [6, 10, 14, 18])
    history = {
        "2024-12-30": DayRecord("2024-12-30", tuple(h2)),
        "2025-01-02": DayRecord("2025-01-02", tuple(h1)),
    }
    dates = ["2024-12-30", "2025-01-02"]
    cached = build_history_context_series(bars=current, history_by_date=history, prior_dates=dates)
    for i in range(len(current)):
        reference = _history_context(bars=current, index=i, history_by_date=history, prior_dates=dates)
        assert cached[i] == reference


def test_cached_context_preserves_missing_prior_date_as_unavailable():
    current = _bars("2025-01-03", [100, 101], [10, 20])
    cached = build_history_context_series(bars=current, history_by_date={}, prior_dates=["2025-01-02"])
    assert cached == [None, None]
