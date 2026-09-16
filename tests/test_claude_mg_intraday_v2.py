from __future__ import annotations

import pytest

from a1clean.formula_research.claude_mg_intraday_v2 import (
    MGIntradayThresholds,
    _constructive_bar_run,
    _evaluate_snapshot,
    _forward_from_bar,
    _intraday_view,
    _precursor_block,
    _process_ticker,
    _reject_oos_source,
)


def _bar(date, *, close, high, low, trade_value=5_000_000.0, nbss=10.0, ts="09:00:00"):
    return {
        "trading_date": date,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000.0,
        "trade_value": trade_value,
        "nbss": nbss,
        # Mirrors packet_to_formula_bars: physical NBSS zero stays UNKNOWN.
        "flow_available": bool(trade_value is not None and nbss is not None and nbss != 0.0),
        "session_eligible": True,
        "timestamp": f"{date} {ts}",
    }


def _flat_day(date, *, close, trade_value):
    """A completed prior day: 4 bars, small range."""
    return {
        "trading_date": date,
        "bars": [
            _bar(date, close=close, high=close * 1.004, low=close * 0.996,
                 trade_value=trade_value / 4, ts=f"09:{i * 5:02d}:00")
            for i in range(4)
        ],
    }


def _precursor_sessions(days=14, start=1000.0):
    """Decline with RISING trade value -- absorption-like, per H03/H04."""
    sessions = []
    price = start
    for d in range(days):
        price *= 0.995
        sessions.append(
            _flat_day(f"2024-12-{d + 1:02d}", close=price, trade_value=3_000_000.0 + d * 400_000.0)
        )
    return sessions, price


def _ignition_day(date, prior_close, *, n_bars=6, step=0.004, trade_value=4_000_000.0, nbss=10.0):
    """Rising intraday path with higher lows, closing at the day high."""
    bars = []
    price = prior_close
    for i in range(n_bars):
        price *= 1.0 + step
        bars.append(
            _bar(date, close=price, high=price, low=price * 0.998,
                 trade_value=trade_value, nbss=nbss, ts=f"09:{i * 5:02d}:00")
        )
    return {"trading_date": date, "bars": bars}


def _thresholds(**overrides):
    base = dict(
        precursor_window_days=8,
        dormant_return_cutoff_pct=0.0,
        flow_persistence_cutoff_ratio=1.0,
        min_absorption_streak_days=2,
        chg_chase_cutoff_pct=10.0,
        min_day_trade_value=1_000_000.0,
        close_location_cutoff=0.6,
        tp1_vol_multiple=1.0,
        tp2_vol_multiple=2.0,
    )
    base.update(overrides)
    return MGIntradayThresholds(**base)


def test_march_source_is_refused_fail_closed():
    for name in ("Raw Mar 01-31-2025.csv", "Raw Maret 2025.csv"):
        with pytest.raises(SystemExit):
            _reject_oos_source(name)
    _reject_oos_source("Raw Des 02-31-2024.csv")


def test_absorption_precursor_then_intraday_wake_fires_with_targets():
    sessions, last = _precursor_sessions()
    sessions.append(_ignition_day("2024-12-15", last))
    signals, rejections, _pools = _process_ticker("TEST", sessions, _thresholds(), [5])

    assert len(signals) == 1, rejections
    signal = signals[0]
    published = signal["published"]
    assert published["chg_pct"] > 0
    assert published["tp2"] > published["tp1"] > published["price"]
    assert signal["absorption_streak_days"] >= 2
    assert signal["timestamp"].startswith("2024-12-15")
    assert signal["future_data_used_for_signal"] is False


def test_fading_flow_precursor_does_not_fire():
    """Decline where value FADES with price is not absorption -- must stay silent."""
    sessions = []
    price = 1000.0
    for d in range(14):
        price *= 0.995
        sessions.append(
            _flat_day(f"2024-12-{d + 1:02d}", close=price, trade_value=max(3_000_000.0 - d * 180_000.0, 200_000.0))
        )
    sessions.append(_ignition_day("2024-12-15", price))
    signals, rejections, _ = _process_ticker("TEST", sessions, _thresholds(), [5])
    assert signals == []
    assert rejections["absorption_streak_too_short"] > 0


def test_forward_bars_cannot_change_the_signal():
    """The leakage test: same history, opposite futures, identical signal."""
    sessions, last = _precursor_sessions()
    day = _ignition_day("2024-12-15", last)

    good = {"trading_date": "2024-12-15", "bars": list(day["bars"])}
    bad = {"trading_date": "2024-12-15", "bars": list(day["bars"])}
    tail_price = day["bars"][-1]["close"]
    for i in range(6):
        good["bars"].append(
            _bar("2024-12-15", close=tail_price * (1.02 + i * 0.01),
                 high=tail_price * (1.03 + i * 0.01), low=tail_price,
                 ts=f"10:{i * 5:02d}:00")
        )
        bad["bars"].append(
            _bar("2024-12-15", close=tail_price * (0.95 - i * 0.01),
                 high=tail_price, low=tail_price * (0.94 - i * 0.01),
                 ts=f"10:{i * 5:02d}:00")
        )

    sig_good, _, _ = _process_ticker("TEST", sessions + [good], _thresholds(), [5])
    sig_bad, _, _ = _process_ticker("TEST", sessions + [bad], _thresholds(), [5])

    assert len(sig_good) == len(sig_bad) == 1
    assert sig_good[0]["bar_index"] == sig_bad[0]["bar_index"]
    assert sig_good[0]["published"] == sig_bad[0]["published"]
    # Outcomes must differ -- proving the futures really were opposite.
    assert sig_good[0]["outcomes"]["5"]["forward_return_pct"] > 0
    assert sig_bad[0]["outcomes"]["5"]["forward_return_pct"] < 0


def test_physical_nbss_zero_is_unknown_not_neutral():
    sessions, last = _precursor_sessions()
    sessions.append(_ignition_day("2024-12-15", last, nbss=0.0))
    signals, rejections, _ = _process_ticker("TEST", sessions, _thresholds(), [5])
    assert signals == []
    assert rejections["stale_or_partial_data"] > 0


def test_mature_chase_is_rejected():
    sessions, last = _precursor_sessions()
    sessions.append(_ignition_day("2024-12-15", last, step=0.05))
    signals, rejections, _ = _process_ticker("TEST", sessions, _thresholds(chg_chase_cutoff_pct=5.0), [5])
    assert signals == []
    assert rejections["mature_chase"] > 0


def test_thin_liquidity_is_rejected():
    sessions, last = _precursor_sessions()
    sessions.append(_ignition_day("2024-12-15", last, trade_value=1_000.0))
    signals, rejections, _ = _process_ticker("TEST", sessions, _thresholds(), [5])
    assert signals == []
    assert rejections["thin_liquidity"] > 0


def test_rejection_giveback_is_rejected():
    """Price closes near the day low after printing a high -- giveback, not MG."""
    sessions, last = _precursor_sessions()
    date = "2024-12-15"
    bars = [
        _bar(date, close=last * 1.03, high=last * 1.05, low=last * 1.00, ts="09:00:00"),
        _bar(date, close=last * 1.005, high=last * 1.05, low=last * 1.00, ts="09:05:00"),
        _bar(date, close=last * 1.004, high=last * 1.05, low=last * 1.00, ts="09:10:00"),
    ]
    sessions.append({"trading_date": date, "bars": bars})
    signals, rejections, _ = _process_ticker("TEST", sessions, _thresholds(), [5])
    assert signals == []
    assert rejections["rejection_giveback"] > 0 or rejections["unstable_path"] > 0


def test_one_bar_spike_without_continuation_is_rejected():
    """A single jump bar followed by a lower low breaks the persistence run."""
    view = {
        "price": 110.0,
        "day_high": 112.0,
        "day_low": 100.0,
        "lows": [100.0, 108.0, 104.0],
        "highs": [101.0, 112.0, 111.0],
        "closes": [100.5, 111.0, 110.0],
        "day_value_so_far": 9_000_000.0,
        "flow_rows": 3,
        "bars_seen": 3,
        "close_location": 0.83,
    }
    assert _constructive_bar_run(view) < 2
    # prior_close kept close to price so the chase gate cannot pre-empt the
    # persistence gate this test is actually about.
    ctx = {
        "absorption_streak_days": 5,
        "prior_structure_high": 150.0,
        "prior_close": 105.0,
        "volatility_unit_pct": 3.0,
    }
    fires, reason, _published = _evaluate_snapshot(view, ctx, _thresholds())
    assert fires is False
    assert reason == "one_bar_spike_no_continuation"


def test_targets_scale_with_measured_volatility_not_a_fixed_percentage():
    view = {
        "price": 100.0, "day_high": 100.0, "day_low": 98.0,
        "lows": [98.0, 99.0, 99.5], "highs": [99.0, 99.8, 100.0],
        "closes": [98.5, 99.5, 100.0],
        "day_value_so_far": 9_000_000.0, "flow_rows": 3, "bars_seen": 3,
        "close_location": 1.0,
    }
    calm = {"absorption_streak_days": 5, "prior_structure_high": 120.0,
            "prior_close": 99.0, "volatility_unit_pct": 1.0}
    wild = {**calm, "volatility_unit_pct": 6.0}

    fires_calm, _r1, calm_pub = _evaluate_snapshot(view, calm, _thresholds())
    fires_wild, _r2, wild_pub = _evaluate_snapshot(view, wild, _thresholds())

    assert fires_calm and fires_wild
    assert wild_pub["tp1"] > calm_pub["tp1"]
    assert calm_pub["tp1"] == pytest.approx(100.0 + 1.0 * 0.01 * 100.0)
    assert wild_pub["tp1"] == pytest.approx(100.0 + 1.0 * 0.06 * 100.0)


def test_forward_evaluation_never_crosses_into_the_next_day():
    date = "2024-12-15"
    bars = [_bar(date, close=100.0 + i, high=101.0 + i, low=99.0 + i) for i in range(3)]
    bars.append(_bar("2024-12-16", close=200.0, high=201.0, low=199.0))
    out = _forward_from_bar(bars, 1, [2], tp1=105.0, tp2=110.0)
    assert out["2"]["evaluable"] is False


def test_one_signal_per_ticker_day_not_one_per_snapshot():
    sessions, last = _precursor_sessions()
    sessions.append(_ignition_day("2024-12-15", last, n_bars=20, step=0.001))
    signals, _rej, _pools = _process_ticker("TEST", sessions, _thresholds(), [5])
    assert len(signals) <= 1
