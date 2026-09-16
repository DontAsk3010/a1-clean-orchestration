from __future__ import annotations

import pytest

from a1clean.formula_research.claude_absorption_wake_v1 import (
    AbsorptionWakeThresholds,
    _daily_from_bars,
    _flow_persistence_ratio,
    _ignition_today,
    _process_ticker,
    _reject_oos_source,
    _trailing_return_pct,
)


def _bar(*, close, high, low, open_=None, trade_value=5_000_000.0, nbss=10.0, flow_available=True):
    return {
        "trading_date": "PLACEHOLDER",
        "open": open_ if open_ is not None else close,
        "high": high,
        "low": low,
        "close": close,
        "trade_value": trade_value,
        "nbss": nbss,
        "flow_available": flow_available,
        "session_eligible": True,
    }


def _session(date: str, *, close, high, low, trade_value, flow_available=True):
    bar = _bar(close=close, high=high, low=low, trade_value=trade_value, flow_available=flow_available)
    bar["trading_date"] = date
    return {"trading_date": date, "bars": [bar]}


def _absorption_then_wake_sessions() -> list[dict]:
    """15 flat/declining days with rising trade value (absorption), then an
    ignition day, then 5 favorable follow-through days."""
    sessions = []
    price = 1000.0
    for day in range(15):
        price *= 0.995  # mild, steady decline -- "habis turun / tidur"
        # trade value RISES across the window even as price falls -- absorption
        tv = 3_000_000.0 + day * 400_000.0
        sessions.append(
            _session(f"2024-12-{day + 1:02d}", close=price, high=price * 1.004, low=price * 0.996, trade_value=tv)
        )
    # ignition day: strong up move, closes at the high, value spike
    ignite_price = price * 1.05
    sessions.append(
        _session("2024-12-16", close=ignite_price, high=ignite_price * 1.001, low=price * 0.999, trade_value=12_000_000.0)
    )
    # favorable follow-through
    follow = ignite_price
    for day in range(5):
        follow *= 1.01
        sessions.append(
            _session(f"2024-12-{17 + day:02d}", close=follow, high=follow * 1.01, low=follow * 0.995, trade_value=8_000_000.0)
        )
    return sessions


def _no_absorption_sessions() -> list[dict]:
    """Declining price where trade value FADES with price -- no absorption."""
    sessions = []
    price = 1000.0
    for day in range(15):
        price *= 0.995
        tv = 3_000_000.0 - day * 150_000.0  # value fades along with price
        sessions.append(
            _session(f"2024-12-{day + 1:02d}", close=price, high=price * 1.004, low=price * 0.996, trade_value=max(tv, 100_000.0))
        )
    ignite_price = price * 1.05
    sessions.append(
        _session("2024-12-16", close=ignite_price, high=ignite_price * 1.001, low=price * 0.999, trade_value=12_000_000.0)
    )
    for day in range(5):
        ignite_price *= 1.01
        sessions.append(
            _session(f"2024-12-{17 + day:02d}", close=ignite_price, high=ignite_price * 1.01, low=ignite_price * 0.995, trade_value=8_000_000.0)
        )
    return sessions


def _thresholds(streak: int = 4) -> AbsorptionWakeThresholds:
    return AbsorptionWakeThresholds(
        precursor_window_days=8,
        dormant_return_cutoff_pct=0.0,  # flat-or-down counts as dormant
        flow_persistence_cutoff_ratio=1.0,  # second half >= first half counts as held
        min_absorption_streak_days=streak,
    )


def test_daily_from_bars_aggregates_session_eligible_only():
    bars = [
        _bar(close=100, high=102, low=99, flow_available=True),
        {**_bar(close=101, high=103, low=100, flow_available=True), "session_eligible": False},
    ]
    daily = _daily_from_bars(bars)
    assert daily is not None
    assert daily["close"] == 100  # the non-eligible bar must not affect the aggregate
    assert daily["flow_available"] is True


def test_trailing_return_and_flow_ratio_require_full_window():
    thresholds = _thresholds()
    sessions = _absorption_then_wake_sessions()
    daily = [d for d in (_daily_from_bars(s["bars"]) for s in sessions) if d is not None]
    assert _trailing_return_pct(daily, 5, thresholds.precursor_window_days) is None  # not enough history yet
    ret = _trailing_return_pct(daily, 10, thresholds.precursor_window_days)
    assert ret is not None and ret < 0  # declining regime correctly measured as negative
    ratio = _flow_persistence_ratio(daily, 10, thresholds.precursor_window_days)
    assert ratio is not None and ratio > 1.0  # flow held up / rose despite price decline


def test_ignition_requires_up_day_and_upper_range_close_and_value_acceleration():
    sessions = _absorption_then_wake_sessions()
    daily = [d for d in (_daily_from_bars(s["bars"]) for s in sessions) if d is not None]
    ignition_idx = 15  # the crafted ignition day
    assert _ignition_today(daily, ignition_idx) is True
    assert _ignition_today(daily, 3) is False  # mid-decline day is not an ignition


def test_absorption_then_wake_fires_and_reports_favorable_forward_outcome():
    sessions = _absorption_then_wake_sessions()
    thresholds = _thresholds(streak=4)
    events, dormant_pool, flow_pool = _process_ticker("TESTX", sessions, thresholds, horizons_days=[1, 3, 5])
    assert dormant_pool and flow_pool  # threshold-learning pools still populate
    assert len(events) == 1, "exactly one first-match ignition event expected"
    event = events[0]
    assert event["absorption_streak_days"] >= 4
    assert event["outcomes"]["3"]["evaluable"] is True
    assert event["outcomes"]["3"]["net_mfe_pct"] > 0  # favorable follow-through, by construction
    assert event["future_data_used_for_signal"] is False
    assert event["future_data_used_for_outcome_only"] is True


def test_price_decline_without_flow_persistence_never_fires():
    sessions = _no_absorption_sessions()
    thresholds = _thresholds(streak=4)
    events, _dormant, _flow = _process_ticker("TESTY", sessions, thresholds, horizons_days=[3])
    assert events == [], "no absorption streak should ever accumulate when flow fades with price"


def test_reserved_oos_source_is_refused_fail_closed():
    with pytest.raises(SystemExit):
        _reject_oos_source("Raw Maret 03-31-2025.csv")
    with pytest.raises(SystemExit):
        _reject_oos_source("raw mar 2025 export.csv")
    _reject_oos_source("Raw Des 02-31-2024.csv")  # must not raise
