from a1clean.formula_research.handbook_candidates import CandidateParams
from a1clean.formula_research.telegram_mg_behavior_topology_v2 import (
    _net_return_pct,
    _observed_step,
    _pullback_reaccel_features,
    _quantile,
)


def _params():
    return CandidateParams(
        effort_lookback=5,
        progress_lookback=5,
        high_lookback=5,
        recovery_lookback=10,
        low_stabilization_bars=3,
        early_checkpoint_bar=30,
        late_lift_min_bar=180,
    )


def test_quantile_and_fee_aware_return():
    assert _quantile([1.0, 2.0, 3.0], 0.5) == 2.0
    assert _net_return_pct(100.0, 101.0, 0.15, 0.25) < 1.0


def test_observed_step_is_prefix_only():
    bars = [
        {"open": 100, "high": 101, "low": 100, "close": 101},
        {"open": 101, "high": 103, "low": 101, "close": 103},
        {"open": 103, "high": 103.5, "low": 103, "close": 103.5},
    ]
    assert _observed_step(bars, 1) == 1.0
    assert _observed_step(bars, 2) == 0.5


def test_pullback_reacceleration_is_causal_and_detects_reclaim():
    closes = [100, 101, 102, 103, 102, 101, 102, 103, 104, 105, 106, 107]
    bars = [
        {"open": c, "high": c + 0.5, "low": c - 0.5, "close": c}
        for c in closes
    ]
    feat = _pullback_reaccel_features(bars, len(bars) - 1, _params())
    assert feat["had_pullback"] is True
    assert feat["reclaim"] is True
    assert feat["renewed_high"] is True
