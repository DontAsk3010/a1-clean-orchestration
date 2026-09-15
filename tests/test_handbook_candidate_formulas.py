from __future__ import annotations

from pathlib import Path

import pytest

from a1clean.formula_research.handbook_candidates import (
    FALSE,
    TRUE,
    UNKNOWN,
    CandidateParams,
    derive_haka_haki,
    evaluate_intraday_candidates,
    evaluate_progressive_h2_h1,
)


def _params(**overrides):
    values = {
        "effort_lookback": 1,
        "progress_lookback": 1,
        "high_lookback": 1,
        "recovery_lookback": 2,
        "low_stabilization_bars": 1,
        "early_checkpoint_bar": 2,
        "late_lift_min_bar": 4,
    }
    values.update(overrides)
    return CandidateParams(**values)


def _bar(
    *,
    o,
    h,
    l,
    c,
    tv=100.0,
    nbss=0.0,
    flow=True,
    mech=True,
    sess=True,
    date="2026-05-29",
    vwap=None,
):
    return {
        "trading_date": date,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "trade_value": tv,
        "nbss": nbss,
        "flow_available": flow,
        "mechanism_eligible": mech,
        "session_eligible": sess,
        "canonical_vwap": vwap,
    }


def test_haka_haki_locked_decomposition_and_reconciliation():
    result = derive_haka_haki(1000, 200, availability_proven=True, mechanism_eligible=True)
    assert result["haka_value_1m"] == pytest.approx(600)
    assert result["haki_value_1m"] == pytest.approx(400)
    assert result["haka_value_1m"] + result["haki_value_1m"] == pytest.approx(1000)
    assert result["haka_value_1m"] - result["haki_value_1m"] == pytest.approx(200)


def test_flow_unavailable_is_unknown_not_zero():
    result = derive_haka_haki(1000, 0, availability_proven=False, mechanism_eligible=True)
    assert result["state"] == UNKNOWN
    assert result["haka_value_1m"] is None
    assert result["haki_value_1m"] is None


def test_f01_buy_stall_basic_and_stricter_variant():
    bars = [
        _bar(o=10, h=11, l=9, c=10.5, tv=100, nbss=10),
        _bar(o=10.5, h=10.9, l=9.8, c=10.4, tv=200, nbss=80),
    ]
    result = evaluate_intraday_candidates(bars, _params())[-1]
    assert result["states"]["F01A_BUY_STALL_BASIC"] == TRUE
    assert result["states"]["F01B_BUY_STALL_STALE_HIGH_EFFORT"] == TRUE


def test_f02_sell_resilience_basic_and_vwap_variant_requires_vwap():
    bars = [
        _bar(o=10, h=10.5, l=9.5, c=10.0, tv=100, nbss=-10),
        _bar(o=10, h=10.6, l=9.6, c=10.1, tv=120, nbss=-50),
    ]
    result = evaluate_intraday_candidates(bars, _params())[-1]
    assert result["states"]["F02A_SELL_RESILIENCE_BASIC"] == TRUE
    assert result["states"]["F02B_SELL_RESILIENCE_ACCEPTANCE_RENEWAL"] == UNKNOWN


def test_f03_new_high_and_high_age_are_causal():
    bars = [
        _bar(o=10, h=10, l=9, c=9.8),
        _bar(o=9.8, h=11, l=9.7, c=10.8),
        _bar(o=10.8, h=10.9, l=10.2, c=10.5),
    ]
    result = evaluate_intraday_candidates(bars, _params())
    assert result[1]["states"]["F03A_NEW_HIGH_EVENT"] == TRUE
    assert result[1]["measurements"]["high_age_bars"] == 0
    assert result[2]["states"]["F03A_NEW_HIGH_EVENT"] == FALSE
    assert result[2]["measurements"]["high_age_bars"] == 1


def test_f04_separates_early_retained_from_late_lift():
    early = [
        _bar(o=10, h=10.1, l=9.9, c=10.0),
        _bar(o=10.0, h=10.4, l=10.0, c=10.3),
        _bar(o=10.3, h=10.5, l=10.2, c=10.4),
        _bar(o=10.4, h=10.6, l=10.3, c=10.5),
    ]
    early_result = evaluate_intraday_candidates(early, _params())[-1]
    assert early_result["states"]["F04A_EARLY_STRENGTH_RETAINED"] == TRUE
    assert early_result["states"]["F04B_LATE_LIFT"] == FALSE

    late = [
        _bar(o=10, h=10.1, l=9.7, c=9.9),
        _bar(o=9.9, h=10.0, l=9.6, c=9.8),
        _bar(o=9.8, h=10.0, l=9.7, c=9.9),
        _bar(o=9.9, h=10.3, l=9.9, c=10.2),
    ]
    late_result = evaluate_intraday_candidates(late, _params())[-1]
    assert late_result["states"]["F04A_EARLY_STRENGTH_RETAINED"] == FALSE
    assert late_result["states"]["F04B_LATE_LIFT"] == TRUE


def test_f05_recovery_requires_prior_weakness_stabilization_reclaim_and_renewed_high():
    bars = [
        _bar(o=10, h=10.0, l=8.0, c=9.0),
        _bar(o=9.0, h=9.2, l=8.1, c=9.0),
        _bar(o=9.0, h=11.0, l=8.5, c=11.0),
    ]
    result = evaluate_intraday_candidates(bars, _params())[-1]
    assert result["states"]["F05A_SESSION_OPEN_RECOVERY"] == TRUE
    assert result["states"]["F05B_CANONICAL_VWAP_RECOVERY"] == UNKNOWN


def test_f06_uses_completed_h2_h1_only():
    sessions = [
        {"trading_date": "2026-05-25", "high": 10, "low": 8, "close": 9, "activity": 100},
        {"trading_date": "2026-05-26", "high": 12, "low": 8, "close": 11, "activity": 200},
        {"trading_date": "2026-05-27", "high": 99, "low": 1, "close": 50, "activity": 9999},
    ]
    result = evaluate_progressive_h2_h1(sessions)
    assert result[2]["F06A_PRICE_PROGRESS"] == TRUE
    assert result[2]["F06B_PRICE_ACTIVITY_PROGRESS"] == TRUE
    assert result[2]["h2_date"] == "2026-05-25"
    assert result[2]["h1_date"] == "2026-05-26"


def test_intraday_prefix_invariance_no_future_backdating():
    prefix = [
        _bar(o=10, h=10.0, l=9.5, c=9.8, tv=100, nbss=20),
        _bar(o=9.8, h=10.1, l=9.6, c=10.0, tv=120, nbss=-20),
        _bar(o=10.0, h=10.2, l=9.9, c=10.1, tv=130, nbss=30),
    ]
    future = _bar(o=10.1, h=20, l=5, c=18, tv=9999, nbss=9000)
    before = evaluate_intraday_candidates(prefix, _params())
    after = evaluate_intraday_candidates(prefix + [future], _params())
    assert after[: len(before)] == before


def test_afl_contains_locked_flow_equations_and_no_trade_orders():
    text = Path("afl/formula_lab/A1_HANDBOOK_CANDIDATE_FORMULA_LAB_V1.afl").read_text(encoding="utf-8")
    compact = "".join(text.split()).lower()
    assert "tradevalue=aux2;" in compact
    assert "nbssvalue=openint;" in compact
    assert "(tradevalue+nbssvalue)/2" in compact
    assert "(tradevalue-nbssvalue)/2" in compact
    assert "timeframegetprice(\"h\",indaily,-1)" in compact
    assert "timeframegetprice(\"h\",indaily,-2)" in compact
    assert "buy=" not in compact
    assert "sell=" not in compact
    assert "short=" not in compact
    assert "cover=" not in compact
