from __future__ import annotations

import pytest

from a1clean.formula_research.claude_mg_openlow_strength_v1 import (
    DEFAULT_RUNGS,
    _day_frame,
    _hhmm,
    _slot_hhmm,
    _money,
    _next_rungs,
    _reject_oos_source,
    _signal_features,
    render_report,
)


def _bar(date, *, open_, high, low, close, tv=5_000_000.0, nbss=10.0, ts="09:00:00"):
    return {
        "trading_date": date,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "trade_value": tv,
        "nbss": nbss,
        "flow_available": nbss != 0.0,
        "session_eligible": True,
        "timestamp": f"{date} {ts}",
    }


def test_march_is_refused_fail_closed():
    for name in ("Raw Mar 01-31-2025.csv", "Raw Maret 2025.csv"):
        with pytest.raises(SystemExit):
            _reject_oos_source(name)
    _reject_oos_source("Raw Des 02-31-2024.csv")


def test_targets_are_the_next_ladder_rungs_above_current_change():
    assert _next_rungs(4.0, DEFAULT_RUNGS) == (5.0, 5.7)
    assert _next_rungs(5.2, DEFAULT_RUNGS) == (5.7, 7.0)
    assert _next_rungs(7.5, DEFAULT_RUNGS) == (10.0, 12.0)


def test_a_signal_already_past_the_top_rung_gets_no_target():
    assert _next_rungs(30.0, DEFAULT_RUNGS) == (None, None)
    assert _next_rungs(21.0, DEFAULT_RUNGS) == (25.0, None)


def test_targets_are_never_below_the_signal_price():
    for chg in (3.6, 4.9, 6.0, 9.9, 11.0):
        tp1, tp2 = _next_rungs(chg, DEFAULT_RUNGS)
        assert tp1 is not None and tp1 > chg
        if tp2 is not None:
            assert tp2 > tp1


def test_day_frame_takes_open_from_the_first_eligible_bar():
    date = "2024-12-03"
    bars = [
        _bar(date, open_=100.0, high=104.0, low=100.0, close=103.0),
        _bar(date, open_=103.0, high=110.0, low=102.0, close=109.0, ts="09:05:00"),
    ]
    frame = _day_frame(bars)
    assert frame["open"] == 100.0
    assert frame["high"] == 110.0
    assert frame["low"] == 100.0


def test_day_frame_rejects_a_day_with_too_few_bars():
    assert _day_frame([_bar("2024-12-03", open_=100.0, high=101.0, low=99.0, close=100.0)]) is None


def test_signal_features_read_only_bars_up_to_the_signal():
    date = "2024-12-03"
    bars = [_bar(date, open_=100.0, high=101.0, low=99.0, close=100.0, tv=1_000_000.0) for _ in range(5)]
    bars.append(_bar(date, open_=100.0, high=110.0, low=100.0, close=109.0, tv=8_000_000.0))
    # A wild future bar that must not influence the features computed at t=5.
    bars.append(_bar(date, open_=109.0, high=500.0, low=1.0, close=400.0, tv=9_000_000.0))

    feats = _signal_features(bars, 5, prior_range_pct=3.0)
    assert feats["bar_index"] == 5
    assert feats["value_expansion"] == pytest.approx(8.0)
    assert feats["close_location"] > 0.8
    # Day range so far uses highs/lows up to bar 5 only: (110-99)/109
    assert feats["day_range_so_far_pct"] == pytest.approx((110.0 - 99.0) / 109.0 * 100.0)


def test_money_formatting_uses_idx_separator_and_keeps_absence_visible():
    assert _money(1610.0) == "1.610"
    assert _money(54.0) == "54"
    assert _money(None) == "—"


def test_hhmm_extracts_clock_time_and_degrades_safely():
    assert _hhmm("2024-12-03 09:25:00") == "09:25"
    assert _hhmm(None) == "??:??"
    assert _hhmm("2024-12-03") == "??:??"


def _payload(result, reached):
    return {
        "source_name": "Raw Des 02-31-2024.csv",
        "strength_target_pct": 10.0,
        "totals": {"signals": 1, "tp1_hits": 1, "tp2_hits": 0, "reached_strength": int(reached),
                   "p_reach_strength_given_signal": 1.0 if reached else 0.0},
        "days": [
            {
                "date": "2024-12-03",
                "scout_count": 548,
                "signal_count": 1,
                "tp1_count": 1,
                "tp2_count": 0,
                "strength_count": int(reached),
                "signals": [
                    {
                        "slot": "09:10",
                        "first_detectable_time": "09:12",
                        "ticker": "AGRO",
                        "price": 234.0,
                        "chg_pct": 3.54,
                        "tp1_price": 236.0,
                        "tp2_price": 238.0,
                        "result": result,
                        "reached_10pct": reached,
                    }
                ],
            }
        ],
    }


def test_report_matches_the_owner_header_and_row_shape():
    text = render_report(_payload("TP1", False), strength_only=False)
    assert "👀 MULAI GENIT" in text
    assert "03 DEC | OPEN=LOW SCOUT 548 | SIGNAL 1 | TP1 1 | TP2 0" in text
    assert "09:10 AGRO" in text
    assert "+3.54%" in text
    assert "TP1✅" in text


def test_a_day_with_no_qualifying_signal_renders_the_governed_zero_match_symbol():
    """Sub-Sub Master section 7: a valid scan with zero results renders ========
    rather than vanishing, so a real zero cannot be confused with a failure."""
    text = render_report(_payload("TP1", False), strength_only=True)
    assert "03 DEC" in text
    assert "========" in text
    assert "STRONG≥10% ONLY" in text


def test_displayed_time_is_the_publication_slot_not_the_bar_minute():
    assert _slot_hhmm("2024-12-03 09:01:00") == "09:00"
    assert _slot_hhmm("2024-12-03 09:07:00") == "09:05"
    assert _slot_hhmm("2024-12-03 10:59:00") == "10:55"
    assert _slot_hhmm(None) == "??:??"


def test_strong_signals_are_starred_and_kept():
    text = render_report(_payload("TP2", True), strength_only=True)
    assert "03 DEC" in text
    assert "★" in text


def test_forward_path_separates_a_rung_miss_that_still_ended_up():
    """A FAIL is only a rung that went untouched. It must not be reported as a
    loss unless the path says so, which is exactly what the owner asked."""
    from a1clean.formula_research.claude_mg_openlow_strength_v1 import _forward_path

    drifted_up = _forward_path(100.0, [
        {"high": 103.0, "low": 99.0, "close": 102.0},
        {"high": 104.0, "low": 101.0, "close": 103.0},
    ])
    assert drifted_up["eod_pct"] == pytest.approx(3.0)
    assert drifted_up["mae_pct"] == pytest.approx(-1.0)
    assert drifted_up["mfe_pct"] == pytest.approx(4.0)

    collapsed = _forward_path(100.0, [
        {"high": 101.0, "low": 95.0, "close": 96.0},
        {"high": 96.0, "low": 90.0, "close": 91.0},
    ])
    assert collapsed["eod_pct"] == pytest.approx(-9.0)
    assert collapsed["mae_pct"] == pytest.approx(-10.0)


def test_drawdown_before_peak_is_measured_up_to_the_best_price_only():
    from a1clean.formula_research.claude_mg_openlow_strength_v1 import _forward_path

    path = _forward_path(100.0, [
        {"high": 101.0, "low": 96.0, "close": 97.0},   # dip before the run
        {"high": 112.0, "low": 100.0, "close": 111.0},  # the peak
        {"high": 111.0, "low": 80.0, "close": 81.0},    # collapse after the peak
    ])
    # The holder endured -4% to reach +12%. The -20% came afterwards and must not
    # be charged against the drawdown-to-peak figure.
    assert path["mae_before_peak_pct"] == pytest.approx(-4.0)
    assert path["mae_pct"] == pytest.approx(-20.0)
    assert path["mfe_pct"] == pytest.approx(12.0)


def test_quantile_returns_a_value_the_sample_actually_contains():
    from a1clean.formula_research.claude_mg_openlow_strength_v1 import _quantile

    sample = [-5.0, -1.0, 0.0, 2.0, 9.0]
    assert _quantile(sample, 0.50) == 0.0
    assert _quantile(sample, 0.10) == -5.0
    assert _quantile(sample, 0.90) == 9.0
    assert _quantile([], 0.5) is None
