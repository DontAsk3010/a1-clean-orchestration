from a1clean.formula_research.telegram_mg_structural_discovery_v3 import _derived, _metric


def _state(**kwargs):
    base = {
        "J01_WAKE_RESPONSE_RETENTION": False,
        "J02_RECOVERY_RECLAIM": False,
        "J03_COMPRESSION_EXPANSION": False,
        "J04_PULLBACK_REACCELERATION": False,
        "J05_FLOW_RESILIENT_CONTINUATION": False,
        "J06_EARLY_STRENGTH_RETAINED": False,
    }
    base.update(kwargs)
    return base


def test_new_wake_requires_transition():
    cur = _state(J01_WAKE_RESPONSE_RETENTION=True)
    assert _derived(cur, [_state()])["K01_NEW_WAKE_RESPONSE"] is True
    assert _derived(cur, [_state(J01_WAKE_RESPONSE_RETENTION=True)])["K01_NEW_WAKE_RESPONSE"] is False


def test_consensus_formulas_are_structural_intersections():
    cur = _state(J01_WAKE_RESPONSE_RETENTION=True, J05_FLOW_RESILIENT_CONTINUATION=True)
    out = _derived(cur, [])
    assert out["K03_WAKE_FLOW_CONSENSUS"] is True
    assert out["K08_MULTI_PATH_CONSENSUS"] is True


def test_early_transition_consensus_needs_two_early_paths():
    cur = _state(J01_WAKE_RESPONSE_RETENTION=True, J03_COMPRESSION_EXPANSION=True)
    assert _derived(cur, [_state()])["K09_EARLY_TRANSITION_CONSENSUS"] is True
    only_one = _state(J01_WAKE_RESPONSE_RETENTION=True)
    assert _derived(only_one, [_state()])["K09_EARLY_TRANSITION_CONSENSUS"] is False


def test_metric_reports_raw_outcome_distribution():
    rows = [
        {"evaluable": True, "net_mfe_pct": -1.0, "eod_net_pct": -2.0, "mae_pct": -3.0},
        {"evaluable": True, "net_mfe_pct": 1.0, "eod_net_pct": 0.5, "mae_pct": -1.0},
        {"evaluable": True, "net_mfe_pct": 3.0, "eod_net_pct": 1.0, "mae_pct": -0.5},
    ]
    m = _metric(rows)
    assert m["candidate_count"] == 3
    assert m["positive_net_mfe_rate"] == 2 / 3
    assert m["net_mfe_q50"] == 1.0
