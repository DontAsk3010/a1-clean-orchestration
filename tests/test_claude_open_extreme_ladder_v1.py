from __future__ import annotations

import pytest

from a1clean.formula_research.claude_open_extreme_ladder_v1 import (
    Counter,
    _cross_was_strong,
    _day_view,
    _first_touch_bar,
    _lift,
    _reject_oos_source,
)


def _bar(date, *, open_, high, low, close, trade_value=5_000_000.0, nbss=10.0):
    return {
        "trading_date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "trade_value": trade_value,
        "nbss": nbss,
        "flow_available": nbss != 0.0,
        "session_eligible": True,
        "timestamp": f"{date} 09:00:00",
    }


def test_march_source_is_refused_fail_closed():
    for name in ("Raw Mar 01-31-2025.csv", "Raw Maret 2025.csv"):
        with pytest.raises(SystemExit):
            _reject_oos_source(name)
    _reject_oos_source("Raw Des 02-31-2024.csv")


def test_day_view_takes_open_from_first_eligible_bar_only():
    date = "2024-12-02"
    bars = [
        _bar(date, open_=100.0, high=104.0, low=100.0, close=103.0),
        _bar(date, open_=103.0, high=110.0, low=102.0, close=109.0),
    ]
    view = _day_view(bars)
    assert view["open"] == 100.0
    assert view["high"] == 110.0
    assert view["low"] == 100.0
    assert view["close"] == 109.0


def test_first_touch_returns_earliest_bar_reaching_the_level():
    date = "2024-12-02"
    bars = [
        _bar(date, open_=100.0, high=101.0, low=99.0, close=100.5),
        _bar(date, open_=100.5, high=103.6, low=100.0, close=103.5),
        _bar(date, open_=103.5, high=106.0, low=103.0, close=105.0),
    ]
    # +3.5% on a prev close of 100 is 103.5, first touched by bar 1.
    assert _first_touch_bar(bars, 103.5, upward=True) == 1
    assert _first_touch_bar(bars, 200.0, upward=True) is None
    assert _first_touch_bar(bars, 99.0, upward=False) == 0


def test_strong_cross_requires_close_in_upper_half_and_value_expansion():
    date = "2024-12-02"
    prior = [_bar(date, open_=100.0, high=101.0, low=99.0, close=100.0, trade_value=1_000_000.0) for _ in range(5)]

    strong = prior + [_bar(date, open_=100.0, high=104.0, low=100.0, close=103.9, trade_value=9_000_000.0)]
    assert _cross_was_strong(strong, 5, upward=True) is True

    # Same breakout level, but price is rejected back to the bar's low.
    rejected = prior + [_bar(date, open_=100.0, high=104.0, low=100.0, close=100.1, trade_value=9_000_000.0)]
    assert _cross_was_strong(rejected, 5, upward=True) is False

    # Upper-half close but no value expansion against the prior bars.
    quiet = prior + [_bar(date, open_=100.0, high=104.0, low=100.0, close=103.9, trade_value=100_000.0)]
    assert _cross_was_strong(quiet, 5, upward=True) is False


def test_unproven_flow_does_not_veto_strength_and_is_never_read_as_zero():
    """NBSS zero means UNKNOWN, so strength falls back to price alone."""
    date = "2024-12-02"
    prior = [_bar(date, open_=100.0, high=101.0, low=99.0, close=100.0, nbss=0.0) for _ in range(5)]
    bars = prior + [_bar(date, open_=100.0, high=104.0, low=100.0, close=103.9, nbss=0.0)]
    assert _cross_was_strong(bars, 5, upward=True) is True


def test_counter_reports_distribution_not_just_a_hit_rate():
    c = Counter()
    for r in (-3.0, -1.0, 0.5, 2.0, 6.0):
        c.add(close_gt_open=r > 0, close_gt_prev=r > 0, day_return_pct=r)
    out = c.as_dict()
    assert out["n"] == 5
    assert out["p_close_above_open"] == pytest.approx(3 / 5)
    assert out["median_day_return_pct"] == pytest.approx(0.5)
    assert out["q10_day_return_pct"] < 0


def test_lift_is_measured_against_baseline_in_percentage_points():
    conditional = {"n": 100, "p_close_above_open": 0.60}
    baseline = {"n": 1000, "p_close_above_open": 0.54}
    assert _lift(conditional, baseline, "p_close_above_open") == pytest.approx(6.0)
    assert _lift({"n": 0}, baseline, "p_close_above_open") is None


def test_empty_counter_reports_nothing_rather_than_a_fabricated_rate():
    assert Counter().as_dict() == {"n": 0}
