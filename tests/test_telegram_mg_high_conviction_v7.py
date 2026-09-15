from a1clean.formula_research.telegram_mg_high_conviction_v7 import _family_hit


def test_v7_fast_clean_label():
    t = {
        "positive_mfe_q75": 3.0,
        "positive_mfe_q85": 5.0,
        "top_winner_fast_q25_bars": 4,
        "top_winner_pre_peak_mae_q50": -0.8,
        "top_winner_reward_to_adverse_q50": 3.0,
    }
    row = {
        "evaluable": True,
        "net_mfe_pct": 4.0,
        "first_positive_net_offset_bars": 2,
        "pre_peak_mae_pct": -0.4,
        "reward_to_pre_peak_adverse": 4.0,
    }
    assert _family_hit(row, "HAKA_FAST_CLEAN", t)


def test_v7_rejects_small_positive_as_high_conviction():
    t = {
        "positive_mfe_q75": 3.0,
        "positive_mfe_q85": 5.0,
        "top_winner_fast_q25_bars": 4,
        "top_winner_pre_peak_mae_q50": -0.8,
        "top_winner_reward_to_adverse_q50": 3.0,
    }
    row = {
        "evaluable": True,
        "net_mfe_pct": 0.2,
        "first_positive_net_offset_bars": 1,
        "pre_peak_mae_pct": -0.1,
        "reward_to_pre_peak_adverse": 4.0,
    }
    assert not _family_hit(row, "HAKA_FAST_CLEAN", t)
    assert not _family_hit(row, "HAKA_STRONG_CLEAN", t)
    assert not _family_hit(row, "HAKA_EFFICIENT", t)
