from a1clean.formula_research.telegram_mg_outcome_first_discovery_v5 import (
    choose_discovery_representative,
    _mine_signatures,
)


def test_choose_discovery_representative_uses_earliest_positive():
    events = [
        {"evaluable": True, "net_mfe_pct": -0.4, "markers": ("A",)},
        {"evaluable": True, "net_mfe_pct": 0.2, "markers": ("B",)},
        {"evaluable": True, "net_mfe_pct": 4.0, "markers": ("C",)},
    ]
    assert choose_discovery_representative(events) is events[1]


def test_choose_discovery_representative_uses_best_failure_when_no_positive():
    events = [
        {"evaluable": True, "net_mfe_pct": -1.2, "markers": ("A",)},
        {"evaluable": True, "net_mfe_pct": -0.3, "markers": ("B",)},
        {"evaluable": True, "net_mfe_pct": -0.8, "markers": ("C",)},
    ]
    assert choose_discovery_representative(events) is events[1]


def test_mine_signatures_is_not_parent_formula_restricted():
    reps = []
    for i in range(30):
        reps.append({
            "evaluable": True,
            "net_mfe_pct": 1.0 if i < 20 else -0.5,
            "mae_pct": -0.2,
            "eod_net_pct": 0.1,
            "markers": ("EARLY_WAKE", "FLOW") if i < 20 else ("NOISE",),
        })
    candidates, summary = _mine_signatures(
        reps,
        min_support=10,
        top_marker_limit=10,
        top_signature_limit=20,
        max_signature_size=2,
    )
    parts = {p for _, rule, _ in candidates for p in rule}
    assert "EARLY_WAKE" in parts or "FLOW" in parts
    assert summary["representative_count"] == 30
