from a1clean.formula_research.outcome_path_quality import evaluate_outcome_path_quality


def test_outcome_path_quality_detects_early_positive_before_later_worst_drawdown():
    bars = [
        {"high": 100.0, "low": 100.0, "close": 100.0},
        {"high": 104.0, "low": 99.0, "close": 103.0},
        {"high": 106.0, "low": 102.0, "close": 105.0},
        {"high": 103.0, "low": 95.0, "close": 96.0},
    ]
    out = evaluate_outcome_path_quality(
        bars=bars,
        signal_index=0,
        entry_proxy=101.0,
        step_proxy=1.0,
        buy_fee_pct=0.15,
        sell_fee_pct=0.25,
    )
    assert out["evaluable"] is True
    assert out["first_positive_net_offset_bars"] == 1
    assert out["peak_offset_bars"] == 2
    assert out["session_worst_offset_bars"] == 3
    assert out["peak_before_session_worst"] is True
    assert out["pre_peak_mae_pct"] < 0
    assert out["net_mfe_pct"] > 0


def test_outcome_path_quality_exposes_deep_adverse_before_recovery_peak():
    bars = [
        {"high": 100.0, "low": 100.0, "close": 100.0},
        {"high": 101.0, "low": 92.0, "close": 93.0},
        {"high": 108.0, "low": 93.0, "close": 107.0},
    ]
    out = evaluate_outcome_path_quality(
        bars=bars,
        signal_index=0,
        entry_proxy=101.0,
        step_proxy=1.0,
        buy_fee_pct=0.15,
        sell_fee_pct=0.25,
    )
    assert out["evaluable"] is True
    assert out["peak_offset_bars"] == 2
    assert out["pre_peak_mae_pct"] < -5.0
    assert out["reward_to_pre_peak_adverse"] is not None


def test_outcome_path_quality_rejects_missing_future_bar_data():
    out = evaluate_outcome_path_quality(
        bars=[{"high": 100.0, "low": 100.0, "close": 100.0}, {"high": None, "low": 99.0, "close": 100.0}],
        signal_index=0,
        entry_proxy=101.0,
        step_proxy=1.0,
        buy_fee_pct=0.15,
        sell_fee_pct=0.25,
    )
    assert out == {"evaluable": False}
