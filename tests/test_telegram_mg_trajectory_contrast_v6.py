from a1clean.formula_research.telegram_mg_trajectory_contrast_v6 import (
    _classifies,
    _label_thresholds,
    _signature_match,
)


def test_signature_match_required_and_forbidden():
    markers = {"A", "B", "C"}
    assert _signature_match(markers, ("A", "B"), ("X",))
    assert not _signature_match(markers, ("A", "D"), ())
    assert not _signature_match(markers, ("A",), ("C",))


def test_label_thresholds_and_classes_are_outcome_only():
    rows = [
        {
            "evaluable": True, "net_mfe_pct": 1.0, "pre_peak_mae_pct": -0.8,
            "first_positive_net_offset_bars": 4, "reward_to_pre_peak_adverse": 1.5,
            "eod_net_pct": 0.5,
        },
        {
            "evaluable": True, "net_mfe_pct": 2.0, "pre_peak_mae_pct": -0.4,
            "first_positive_net_offset_bars": 2, "reward_to_pre_peak_adverse": 4.0,
            "eod_net_pct": 1.2,
        },
        {
            "evaluable": True, "net_mfe_pct": 4.0, "pre_peak_mae_pct": -0.2,
            "first_positive_net_offset_bars": 1, "reward_to_pre_peak_adverse": 10.0,
            "eod_net_pct": 3.0,
        },
    ]
    t = _label_thresholds(rows)
    assert t["positive_mfe_q50"] == 2.0
    assert _classifies(rows[1], "ANY_POSITIVE", t)
    assert _classifies(rows[2], "STRONG_RUNNER", t)


def test_negative_event_never_classifies_positive_family():
    t = {
        "positive_mfe_q50": 1.0,
        "positive_mfe_q75": 2.0,
        "clean_pre_peak_mae_q50": -1.0,
        "fast_first_positive_q50_bars": 5,
        "reward_to_adverse_q50": 2.0,
        "retained_fraction_q50": 0.5,
    }
    row = {
        "evaluable": True, "net_mfe_pct": -0.1, "pre_peak_mae_pct": -0.2,
        "first_positive_net_offset_bars": None, "reward_to_pre_peak_adverse": None,
        "eod_net_pct": -0.2,
    }
    for family in ("ANY_POSITIVE", "FAST_CLEAN", "STRONG_RUNNER", "RETAINED_WINNER"):
        assert not _classifies(row, family, t)
