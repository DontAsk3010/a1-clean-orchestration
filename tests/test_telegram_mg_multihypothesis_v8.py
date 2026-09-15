from a1clean.formula_research import telegram_mg_multihypothesis_v8b as v8b
from a1clean.formula_research import telegram_mg_multihypothesis_v8c as v8c


def _cuts(*pairs):
    return list(pairs)


def test_named_sideways_pullback_and_ignition_markers_are_formed_from_frozen_quantiles():
    thresholds = {
        "pre3_close_span_pct": _cuts(("q25", 1.0), ("q35", 1.5)),
        "pre5_close_span_pct": _cuts(("q25", 1.2), ("q35", 1.8)),
        "pre5_prior_peak_gain_pct": _cuts(("q75", 8.0),),
        "pre5_pullback_from_peak_pct": _cuts(("q25", -4.0),),
        "pre3_range_contraction": _cuts(("q25", 0.7),),
        "pre5_value_trend_ratio": _cuts(("q75", 1.8),),
        "pre5_volume_trend_ratio": _cuts(("q75", 1.6),),
        "ign_value_ratio": _cuts(("q75", 2.0),),
        "ign_volume_ratio": _cuts(("q75", 1.8),),
        "ign_path_delta_pct": _cuts(("q75", 2.5),),
        "cur_close_location": _cuts(("q75", 0.8),),
    }
    event = {
        "features": {
            "pre3_close_span_pct": 0.8,
            "pre5_close_span_pct": 1.0,
            "pre5_prior_peak_gain_pct": 10.0,
            "pre5_pullback_from_peak_pct": -6.0,
            "pre3_range_contraction": 0.5,
            "pre5_value_trend_ratio": 2.2,
            "pre5_volume_trend_ratio": 2.0,
            "ign_value_ratio": 2.4,
            "ign_volume_ratio": 2.1,
            "ign_path_delta_pct": 3.0,
            "cur_close_location": 0.9,
        }
    }
    markers = v8b._marker_set(event, thresholds)
    assert "PRE_SIDEWAYS_3D" in markers
    assert "PRE_SIDEWAYS_5D" in markers
    assert "PRE_RANGE_COMPRESSION" in markers
    assert "PRE_VALUE_BUILD_SIDEWAYS" in markers
    assert "PRE_VOLUME_BUILD_SIDEWAYS" in markers
    assert "PRE_RISE_PULLBACK_BASE_5D" in markers
    assert "IGN_VALUE_WAKE" in markers
    assert "IGN_VOLUME_WAKE" in markers
    assert "IGN_PATH_OUTPERFORMANCE" in markers
    assert "IGN_HIGH_ACCEPTANCE" in markers


def test_outcome_label_thresholds_are_discovery_driven_not_fixed_constants():
    events = []
    for i, mfe in enumerate([0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0]):
        events.append({
            "evaluable": True,
            "net_mfe_pct": mfe,
            "first_positive_net_offset_bars": i + 1,
            "pre_peak_mae_pct": -0.1 * i,
            "reward_to_pre_peak_adverse": 1.0 + i,
            "eod_net_pct": mfe * 0.5,
        })
    t = v8b._label_thresholds(events)
    assert t["mfe_q65"] is not None
    assert t["mfe_q80"] is not None
    assert t["strong_first_positive_q50_bars"] is not None
    assert t["strong_pre_peak_mae_q50"] is not None
    assert t["strong_reward_to_adverse_q50"] is not None
    assert t["strong_retained_fraction_q50"] is not None


def test_strict_miner_candidates_always_combine_precursor_and_ignition():
    thresholds = {
        "pre3_close_span_pct": _cuts(("q25", 1.0), ("q35", 1.5)),
        "ign_value_ratio": _cuts(("q75", 2.0),),
    }
    events = []
    for i in range(80):
        winner = i < 40
        events.append({
            "date": f"2025-01-{(i % 28) + 1:02d}",
            "ticker": f"T{i:03d}",
            "evaluable": True,
            "net_mfe_pct": 5.0 if winner else -1.0,
            "features": {
                "pre3_close_span_pct": 0.5 if winner else 2.0,
                "ign_value_ratio": 3.0 if winner else 1.0,
            },
        })
    label = {"mfe_q80": 4.0, "mfe_q65": 3.0}
    mined = v8c._mine_strict(
        events, thresholds, label, "EXPLOSIVE",
        min_support=10, min_unique_days=10, top_each=10, top_formulas=20,
    )
    assert mined["candidates"]
    for candidate in mined["candidates"]:
        req = candidate["required"]
        assert any(x.startswith("PRE_") for x in req)
        assert any(x.startswith("IGN_") for x in req)
        assert candidate["precision_lift_vs_family_base"] > 0
