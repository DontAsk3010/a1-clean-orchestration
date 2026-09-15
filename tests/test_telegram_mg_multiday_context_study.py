from __future__ import annotations

from a1clean.formula_research.telegram_mg_multiday_context_study import (
    DayRecord,
    _history_context,
    _mode_matches,
)


def _bar(*, close: float, high: float, low: float, value: float, s1: bool = True, s2: bool = False):
    return {
        "close": close,
        "high": high,
        "low": low,
        "trade_value": value,
        "regular_session1": s1,
        "regular_session2": s2,
    }


def test_history_context_detects_activity_range_and_path_wake():
    prior_1 = DayRecord(
        "2024-12-02",
        (
            _bar(close=100, high=101, low=99, value=10),
            _bar(close=100, high=101, low=99, value=10),
            _bar(close=101, high=102, low=99, value=10),
        ),
    )
    prior_2 = DayRecord(
        "2024-12-03",
        (
            _bar(close=100, high=101, low=99, value=12),
            _bar(close=101, high=102, low=99, value=12),
            _bar(close=101, high=102, low=99, value=12),
        ),
    )
    current = [
        _bar(close=100, high=101, low=99, value=20),
        _bar(close=102, high=103, low=99, value=20),
        _bar(close=104, high=105, low=99, value=20),
    ]
    context = _history_context(
        bars=current,
        index=2,
        history_by_date={prior_1.trading_date: prior_1, prior_2.trading_date: prior_2},
        prior_dates=["2024-12-02", "2024-12-03"],
    )
    assert context is not None
    assert context["activity_wake"] is True
    assert context["range_wake"] is True
    assert context["path_wake"] is True
    assert _mode_matches(context, "ACTIVITY_RANGE_PATH_WAKE") is True


def test_history_context_requires_exact_prior_dates_and_same_segment_capacity():
    prior = DayRecord(
        "2024-12-02",
        (
            _bar(close=100, high=101, low=99, value=10, s1=False, s2=True),
        ),
    )
    current = [
        _bar(close=100, high=101, low=99, value=20, s1=False, s2=True),
        _bar(close=101, high=102, low=99, value=20, s1=False, s2=True),
    ]
    assert _history_context(
        bars=current,
        index=1,
        history_by_date={prior.trading_date: prior},
        prior_dates=["2024-12-02"],
    ) is None
    assert _history_context(
        bars=current,
        index=0,
        history_by_date={prior.trading_date: prior},
        prior_dates=["2024-12-01"],
    ) is None


def test_path_wake_is_relative_to_prior_baseline_not_absolute_clock_return():
    prior = DayRecord(
        "2024-12-02",
        (
            _bar(close=100, high=101, low=99, value=10),
            _bar(close=104, high=105, low=99, value=10),
        ),
    )
    current = [
        _bar(close=100, high=101, low=99, value=20),
        _bar(close=102, high=103, low=99, value=20),
    ]
    context = _history_context(
        bars=current,
        index=1,
        history_by_date={prior.trading_date: prior},
        prior_dates=["2024-12-02"],
    )
    assert context is not None
    assert context["activity_wake"] is True
    assert context["path_wake"] is False
    assert _mode_matches(context, "ACTIVITY_PATH_WAKE") is False
