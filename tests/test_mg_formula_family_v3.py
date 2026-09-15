from a1clean.formula_research.mg_formula_family_v3 import evaluate_mg_formula_family


def _base_state():
    return {
        "ACTIVITY_WAKE": True,
        "RANGE_WAKE": True,
        "PATH_WAKE": True,
        "UP_PATH": True,
        "PERSISTENCE": True,
        "ACCEPTANCE": True,
        "VALUE_EXPANSION": True,
        "CONSTRUCTIVE_FLOW": True,
        "ANTI_BUY_STALL": True,
        "FRESH_HIGH": True,
        "EARLY_STRENGTH_RETAINED": True,
        "RECOVERY_RUNNER": False,
        "LATE_LIFT": False,
        "HAD_PULLBACK": False,
        "RECLAIM": False,
        "RENEWED_HIGH": False,
        "STRUCTURE_LOSS": False,
        "SESSION_SAFE": True,
        "DATA_COMPLETE": True,
        "EXECUTION_READY": True,
        "PROFIT_ROOM_PASS": True,
    }


def test_multiple_positive_paths_can_coexist_but_final_gate_is_common():
    result = evaluate_mg_formula_family(_base_state())
    assert result["paths"]["P01_WAKE_RESPONSE_RETENTION"] is True
    assert result["paths"]["P03_COMPRESSION_EXPANSION"] is True
    assert result["paths"]["P05_FLOW_RESILIENT_CONTINUATION"] is True
    assert result["paths"]["P06_EARLY_STRENGTH_RETAINED"] is True
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is True


def test_recovery_path_can_qualify_without_wake_path():
    state = _base_state()
    state.update({
        "ACTIVITY_WAKE": False,
        "RANGE_WAKE": False,
        "PATH_WAKE": False,
        "UP_PATH": False,
        "PERSISTENCE": False,
        "CONSTRUCTIVE_FLOW": False,
        "EARLY_STRENGTH_RETAINED": False,
        "RECOVERY_RUNNER": True,
    })
    result = evaluate_mg_formula_family(state)
    assert result["paths"]["P02_RECOVERY_RECLAIM"] is True
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is True


def test_pullback_reacceleration_is_a_distinct_path():
    state = _base_state()
    state.update({
        "ACTIVITY_WAKE": False,
        "RANGE_WAKE": False,
        "PATH_WAKE": False,
        "UP_PATH": False,
        "CONSTRUCTIVE_FLOW": False,
        "EARLY_STRENGTH_RETAINED": False,
        "FRESH_HIGH": False,
        "HAD_PULLBACK": True,
        "RECLAIM": True,
        "RENEWED_HIGH": True,
    })
    result = evaluate_mg_formula_family(state)
    assert result["paths"]["P04_PULLBACK_REACCELERATION"] is True
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is True


def test_trap_blocks_all_positive_paths():
    state = _base_state()
    state["STRUCTURE_LOSS"] = True
    result = evaluate_mg_formula_family(state)
    assert result["gates"]["BEHAVIOR_PATH_OK"] is True
    assert result["negative_formulas"]["N03_STRUCTURE_FAILURE"] is True
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is False


def test_signal_is_not_entry_and_profit_room_is_separate():
    state = _base_state()
    state["EXECUTION_READY"] = False
    result = evaluate_mg_formula_family(state)
    assert result["gates"]["MG_BEHAVIOR_CANDIDATE"] is True
    assert result["gates"]["MG_EXECUTION_CANDIDATE"] is False
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is False

    state["EXECUTION_READY"] = True
    state["PROFIT_ROOM_PASS"] = False
    result = evaluate_mg_formula_family(state)
    assert result["gates"]["MG_EXECUTION_CANDIDATE"] is True
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is False


def test_missing_data_is_block_not_zero_or_neutral():
    state = _base_state()
    state["DATA_COMPLETE"] = False
    result = evaluate_mg_formula_family(state)
    assert result["negative_formulas"]["N04_DATA_OR_SESSION_BLOCK"] is True
    assert result["gates"]["MG_PROFIT_QUALIFIED"] is False
