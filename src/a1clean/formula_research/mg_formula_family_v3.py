from __future__ import annotations

from typing import Any, Mapping


FORMULA_IDS = (
    "P01_WAKE_RESPONSE_RETENTION",
    "P02_RECOVERY_RECLAIM",
    "P03_COMPRESSION_EXPANSION",
    "P04_PULLBACK_REACCELERATION",
    "P05_FLOW_RESILIENT_CONTINUATION",
    "P06_EARLY_STRENGTH_RETAINED",
)

NEGATIVE_IDS = (
    "N01_BUY_STALL_TRAP",
    "N02_LATE_CHASE_TRAP",
    "N03_STRUCTURE_FAILURE",
    "N04_DATA_OR_SESSION_BLOCK",
)


def _b(state: Mapping[str, Any], key: str) -> bool:
    """Strict research boolean: missing/unavailable is never silently True.

    Upstream governed feature builders remain responsible for preserving
    UNKNOWN separately. This combinator only accepts normalized proven booleans.
    """
    return state.get(key) is True


def evaluate_behavior_paths(state: Mapping[str, Any]) -> dict[str, bool]:
    activity_wake = _b(state, "ACTIVITY_WAKE")
    range_wake = _b(state, "RANGE_WAKE")
    path_wake = _b(state, "PATH_WAKE")
    up_path = _b(state, "UP_PATH")
    persistence = _b(state, "PERSISTENCE")
    acceptance = _b(state, "ACCEPTANCE")
    value_expansion = _b(state, "VALUE_EXPANSION")
    constructive_flow = _b(state, "CONSTRUCTIVE_FLOW")
    anti_stall = _b(state, "ANTI_BUY_STALL")
    fresh_high = _b(state, "FRESH_HIGH")
    early_retained = _b(state, "EARLY_STRENGTH_RETAINED")
    recovery_runner = _b(state, "RECOVERY_RUNNER")
    late_lift = _b(state, "LATE_LIFT")
    had_pullback = _b(state, "HAD_PULLBACK")
    reclaim = _b(state, "RECLAIM")
    renewed_high = _b(state, "RENEWED_HIGH")

    return {
        "P01_WAKE_RESPONSE_RETENTION": (
            activity_wake
            and path_wake
            and up_path
            and persistence
            and acceptance
            and value_expansion
            and anti_stall
            and not late_lift
        ),
        "P02_RECOVERY_RECLAIM": (
            recovery_runner
            and acceptance
            and value_expansion
            and fresh_high
            and anti_stall
        ),
        "P03_COMPRESSION_EXPANSION": (
            activity_wake
            and range_wake
            and path_wake
            and up_path
            and acceptance
            and value_expansion
            and fresh_high
            and anti_stall
        ),
        "P04_PULLBACK_REACCELERATION": (
            had_pullback
            and reclaim
            and renewed_high
            and persistence
            and acceptance
            and value_expansion
            and anti_stall
        ),
        "P05_FLOW_RESILIENT_CONTINUATION": (
            up_path
            and persistence
            and acceptance
            and value_expansion
            and constructive_flow
            and anti_stall
            and fresh_high
        ),
        "P06_EARLY_STRENGTH_RETAINED": (
            path_wake
            and early_retained
            and persistence
            and acceptance
            and fresh_high
            and anti_stall
            and not late_lift
        ),
    }


def evaluate_negative_formulas(state: Mapping[str, Any]) -> dict[str, bool]:
    anti_stall_known = "ANTI_BUY_STALL" in state and state.get("ANTI_BUY_STALL") is not None
    buy_stall = anti_stall_known and not _b(state, "ANTI_BUY_STALL")
    late_lift = _b(state, "LATE_LIFT")
    structure_loss = _b(state, "STRUCTURE_LOSS")
    data_complete = _b(state, "DATA_COMPLETE")
    session_safe = _b(state, "SESSION_SAFE")

    return {
        "N01_BUY_STALL_TRAP": buy_stall,
        "N02_LATE_CHASE_TRAP": late_lift,
        "N03_STRUCTURE_FAILURE": structure_loss,
        "N04_DATA_OR_SESSION_BLOCK": (not data_complete) or (not session_safe),
    }


def evaluate_mg_formula_family(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = evaluate_behavior_paths(state)
    negatives = evaluate_negative_formulas(state)

    behavior_path_ok = any(paths.values())
    trap_free = not any(negatives.values())
    behavior_candidate = behavior_path_ok and trap_free
    execution_ready = _b(state, "EXECUTION_READY")
    profit_room_pass = _b(state, "PROFIT_ROOM_PASS")
    execution_candidate = behavior_candidate and execution_ready
    profit_qualified = execution_candidate and profit_room_pass

    return {
        "paths": paths,
        "negative_formulas": negatives,
        "gates": {
            "BEHAVIOR_PATH_OK": behavior_path_ok,
            "TRAP_FREE": trap_free,
            "MG_BEHAVIOR_CANDIDATE": behavior_candidate,
            "MG_EXECUTION_CANDIDATE": execution_candidate,
            "MG_PROFIT_QUALIFIED": profit_qualified,
        },
        "matched_paths": [formula_id for formula_id, passed in paths.items() if passed],
        "blocking_formulas": [formula_id for formula_id, blocked in negatives.items() if blocked],
    }
