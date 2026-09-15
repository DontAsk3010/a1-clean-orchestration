from a1clean.formula_research.telegram_family_formula_v1 import (
    evaluate_acceleration,
    evaluate_ara_imminent,
    evaluate_buy_ready,
    evaluate_multibagger,
    evaluate_overnight,
    evaluate_pullback,
    evaluate_swing_buy,
)


def test_buy_ready_is_independent_and_requires_execution_geometry():
    s = {
        "BREAKOUT_EVENT": True,
        "HOLD_ABOVE_REFERENCE": True,
        "ACCEPTANCE": True,
        "PARTICIPATION_ADEQUATE": True,
        "RESPONSE_EFFICIENT": True,
        "ENTRY_AREA_DEFINED": True,
        "INVALIDATION_DEFINED": True,
        "EXECUTION_READY": True,
        "SAME_DAY_REWARD_ROOM": True,
    }
    out = evaluate_buy_ready(s)
    assert out["pass"] is True
    assert out["matched_paths"] == ["BR01_BREAKOUT_ACCEPTANCE"]


def test_acceleration_blocks_one_bar_spike_even_when_path_matches():
    s = {
        "PRIOR_COMPRESSION": True,
        "RATE_OF_CHANGE_EXPANDS": True,
        "RANGE_EXPANDS_DIRECTIONALLY": True,
        "PARTICIPATION_EXPANDS": True,
        "RETENTION": True,
        "SAME_DAY_CONTINUATION_ROOM": True,
        "EXECUTION_READY": True,
        "ONE_BAR_SPIKE_ONLY": True,
    }
    out = evaluate_acceleration(s)
    assert out["matched_paths"] == ["AC01_COMPRESSION_EXPANSION"]
    assert out["pass"] is False


def test_ara_imminent_has_own_near_path_without_ara_potential_dependency():
    s = {
        "ARA_BOUNDARY_VALID": True,
        "NEAR_BOUNDARY": True,
        "FINAL_PATH_STRENGTH": True,
        "PERSISTENCE": True,
        "PARTICIPATION_ADEQUATE": True,
    }
    out = evaluate_ara_imminent(s)
    assert out["pass"] is True
    assert out["status"] == "NEAR"


def test_swing_buy_requires_actionable_window_now():
    s = {
        "VALID_SWING_JOURNEY": True,
        "CONTROLLED_RETRACEMENT": True,
        "STABILIZATION_AND_RECLAIM": True,
        "ENTRY_STILL_ACTIONABLE": True,
        "INVALIDATION_DEFINED": True,
        "REMAINING_SWING_ROOM": True,
    }
    assert evaluate_swing_buy(s)["pass"] is True
    s["ENTRY_WINDOW_PASSED"] = True
    assert evaluate_swing_buy(s)["pass"] is False


def test_multibagger_is_remaining_journey_not_historical_x2():
    s = {
        "VALID_FOUNDATION_OR_BASE": True,
        "PERSISTENT_PARTICIPATION": True,
        "EXPANSION_QUALITY": True,
        "HIGHER_STRUCTURAL_BASES": True,
        "LARGE_REMAINING_ROOM": True,
        "REFERENCE_BASIS_VALID": True,
        "CREDIBLE_REMAINING_X2_PLUS": True,
    }
    assert evaluate_multibagger(s)["pass"] is True
    s["HISTORICAL_X2_ALREADY_SPENT_WITHOUT_REMAINING_ROOM"] = True
    assert evaluate_multibagger(s)["pass"] is False


def test_pullback_rejects_falling_knife():
    s = {
        "VALID_PRIMARY_JOURNEY": True,
        "CONTROLLED_RETRACEMENT": True,
        "THESIS_ALIVE": True,
        "SELLING_NOT_DOMINANT": True,
        "STABILIZATION": True,
        "RECLAIM": True,
        "PRIMARY_THESIS_ALIVE": True,
        "REENTRY_ACTIONABLE": True,
        "FALLING_KNIFE": True,
    }
    out = evaluate_pullback(s)
    assert out["matched_paths"] == ["PB01_CONTROLLED_RETRACE_RECLAIM"]
    assert out["pass"] is False


def test_overnight_h1_is_family_specific():
    s = {
        "LATE_SESSION": True,
        "VALID_SWING_JOURNEY": True,
        "PROGRESS_RETAINED": True,
        "CLOSE_QUALITY_CONTEXT_STRONG": True,
        "PARTICIPATION_SUPPORT": True,
        "H1_CARRY_RISK_ACCEPTABLE": True,
        "THESIS_DURABLE": True,
    }
    assert evaluate_overnight(s)["pass"] is True
