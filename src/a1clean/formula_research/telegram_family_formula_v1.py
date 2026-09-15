from __future__ import annotations

from typing import Any, Mapping


def _b(state: Mapping[str, Any], key: str) -> bool:
    return state.get(key) is True


def _all(state: Mapping[str, Any], *keys: str) -> bool:
    return all(_b(state, k) for k in keys)


def _none(state: Mapping[str, Any], *keys: str) -> bool:
    return not any(_b(state, k) for k in keys)


def evaluate_buy_ready(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "BR01_BREAKOUT_ACCEPTANCE": _all(state, "BREAKOUT_EVENT", "HOLD_ABOVE_REFERENCE", "ACCEPTANCE", "PARTICIPATION_ADEQUATE", "RESPONSE_EFFICIENT"),
        "BR02_PULLBACK_RECLAIM_ENTRY": _all(state, "VALID_INTRADAY_JOURNEY", "CONTROLLED_PULLBACK", "RECLAIM", "SUPPORT_RESPONSE", "ACCEPTANCE"),
        "BR03_RELOAD_CONTINUATION_ENTRY": _all(state, "VALID_INTRADAY_JOURNEY", "CONSOLIDATION_OR_RELOAD", "RENEWED_PROGRESS", "PARTICIPATION_ADEQUATE", "RETENTION"),
        "BR04_SUPPORT_REACCEPTANCE": _all(state, "VALID_INTRADAY_JOURNEY", "SUPPORT_TEST", "REACCEPTANCE", "SELL_PRESSURE_NOT_DOMINANT", "RETENTION"),
        "BR05_TREND_CONTINUATION_ENTRY": _all(state, "EFFICIENT_UP_PATH", "CONTROLLED_RISK_GEOMETRY", "FRESH_PROGRESS", "PARTICIPATION_ADEQUATE", "NOT_OVEREXTENDED"),
    }
    blocks = {
        "LATE_CHASE": _b(state, "LATE_CHASE"),
        "FAILED_BREAKOUT_OR_RECLAIM": _b(state, "FAILED_BREAKOUT_OR_RECLAIM"),
        "RISK_BOUNDARY_UNDEFINED_OR_TOO_REMOTE": _b(state, "RISK_BOUNDARY_UNDEFINED_OR_TOO_REMOTE"),
        "INSUFFICIENT_SAME_DAY_REWARD_ROOM": _b(state, "INSUFFICIENT_SAME_DAY_REWARD_ROOM"),
        "POOR_EFFORT_RESPONSE": _b(state, "POOR_EFFORT_RESPONSE"),
        "ILLIQUID_OR_UNSTABLE_EXECUTION": _b(state, "ILLIQUID_OR_UNSTABLE_EXECUTION"),
        "DATA_INVALID": _b(state, "DATA_INVALID"),
    }
    passed = any(paths.values()) and _all(state, "ENTRY_AREA_DEFINED", "INVALIDATION_DEFINED", "EXECUTION_READY", "SAME_DAY_REWARD_ROOM") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_acceleration(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "AC01_COMPRESSION_EXPANSION": _all(state, "PRIOR_COMPRESSION", "RATE_OF_CHANGE_EXPANDS", "RANGE_EXPANDS_DIRECTIONALLY", "PARTICIPATION_EXPANDS", "RETENTION"),
        "AC02_PULLBACK_REACCELERATION": _all(state, "CONTROLLED_PAUSE_OR_PULLBACK", "RECLAIM", "VELOCITY_RENEWAL", "HIGH_PROGRESS_ACCELERATES", "RETENTION"),
        "AC03_BREAKOUT_VELOCITY_EXPANSION": _all(state, "BREAKOUT_EVENT", "MULTIBAR_VELOCITY_INCREASE", "FRESH_HIGH_RATE_INCREASE", "PARTICIPATION_SUPPORT"),
        "AC04_RECLAIM_ACCELERATION": _all(state, "PRIOR_WEAK_OR_NEUTRAL_STATE", "RECLAIM", "PROGRESS_RATE_INCREASE", "PARTICIPATION_SUPPORT", "RETENTION"),
        "AC05_EFFORT_EFFICIENT_SLOPE_EXPANSION": _all(state, "EFFORT_EXPANDS", "PRICE_RESPONSE_EFFICIENCY_IMPROVES", "PATH_SLOPE_INCREASES", "PERSISTENCE"),
    }
    block_names = (
        "ONE_BAR_SPIKE_ONLY", "BLOW_OFF_OR_CLIMAX", "REPEATED_FAILED_HIGHS", "POOR_EFFORT_RESPONSE",
        "TERMINAL_EXTENSION", "ILLIQUID_ARTIFICIAL_VELOCITY", "RAPID_MEAN_REVERSION", "DATA_INVALID",
    )
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _all(state, "SAME_DAY_CONTINUATION_ROOM", "EXECUTION_READY") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_ara_potential(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "AP01_RETAINED_DISTANCE_COMPRESSION": _all(state, "ARA_BOUNDARY_VALID", "DISTANCE_TO_ARA_COMPRESSING", "PATH_CONTINUITY", "RETENTION", "PARTICIPATION_ADEQUATE"),
        "AP02_REACCELERATING_ROUTE": _all(state, "ARA_BOUNDARY_VALID", "CONTROLLED_PAUSE", "REACCELERATION", "DISTANCE_TO_ARA_COMPRESSING", "RETENTION"),
        "AP03_HIGH_LIFECYCLE_ROUTE": _all(state, "ARA_BOUNDARY_VALID", "REPEATED_FRESH_HIGHS", "LIMITED_GIVEBACK", "DISTANCE_TO_ARA_COMPRESSING"),
        "AP04_EFFICIENT_EFFORT_ROUTE": _all(state, "ARA_BOUNDARY_VALID", "PARTICIPATION_EXPANDS", "EFFORT_RESPONSE_EFFICIENT", "DISTANCE_TO_ARA_COMPRESSING"),
        "AP05_RECOVERY_ROUTE_RESTORED": _all(state, "ARA_BOUNDARY_VALID", "PRIOR_ROUTE_WEAKENED", "RECLAIM", "ROUTE_STRENGTH_RESTORED", "DISTANCE_TO_ARA_COMPRESSING"),
    }
    block_names = (
        "ARA_REFERENCE_INVALID", "SUPERFICIAL_PROXIMITY_ONLY", "REPEATED_NEAR_BOUNDARY_REJECTION",
        "EFFORT_CLIMAX_WITH_SHRINKING_PROGRESS", "TERMINAL_EXTENSION", "INSUFFICIENT_REMAINING_SESSION_ROUTE",
        "ILLIQUID_FALSE_PROXIMITY", "DATA_INVALID",
    )
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _all(state, "ARA_BOUNDARY_VALID", "SAME_DAY_ROUTE_FEASIBLE") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_ara_imminent(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "AI01_FINAL_DISTANCE_COMPRESSION": _all(state, "ARA_BOUNDARY_VALID", "NEAR_BOUNDARY", "FINAL_PATH_STRENGTH", "PERSISTENCE", "PARTICIPATION_ADEQUATE"),
        "AI02_REJECTION_ABSORPTION": _all(state, "ARA_BOUNDARY_VALID", "NEAR_BOUNDARY", "PRIOR_REJECTION", "FAST_RECLAIM", "REJECTION_WEAKENS", "FINAL_PROGRESS"),
        "AI03_FINAL_REACCELERATION": _all(state, "ARA_BOUNDARY_VALID", "NEAR_BOUNDARY", "REACCELERATION", "HIGH_PROGRESS_ACCELERATES", "RETENTION"),
        "AI04_ROBUST_NEAR_BOUNDARY_PERSISTENCE": _all(state, "ARA_BOUNDARY_VALID", "VERY_SMALL_REMAINING_DISTANCE", "RETENTION", "EFFORT_RESPONSE_EFFICIENT", "NO_DOMINANT_REJECTION"),
        "AI05_ARA_TOUCH_PERSISTENCE": _all(state, "ARA_REACHED", "ARA_STATE_PERSISTS", "RELEASE_RISK_NOT_DOMINANT"),
    }
    block_names = (
        "ARA_REFERENCE_INVALID", "PROXIMITY_WITH_WEAKENING_PROGRESS", "FINAL_BLOW_OFF_RELEASE",
        "MOMENTARY_UNSTABLE_TOUCH", "EFFORT_WITHOUT_FINAL_PROGRESS", "ILLIQUID_FALSE_NEAR_STATE", "DATA_INVALID",
    )
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _b(state, "ARA_BOUNDARY_VALID") and not any(blocks.values())
    result = _result(paths, blocks, passed)
    result["status"] = "ARA" if passed and _b(state, "ARA_REACHED") and _b(state, "ARA_STATE_PERSISTS") else ("NEAR" if passed else None)
    return result


def evaluate_swing_buy(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "SB01_DEVELOPING_DAILY_BREAKOUT_ACCEPTANCE": _all(state, "PRIOR_DAILY_BASE_OR_STRUCTURE", "DEVELOPING_DAILY_BREAKOUT", "ACCEPTANCE", "PARTICIPATION_SUPPORT", "ENTRY_STILL_ACTIONABLE"),
        "SB02_DEVELOPING_DAILY_RECLAIM": _all(state, "PRIOR_DAILY_WEAK_OR_NEUTRAL_STATE", "DEVELOPING_DAILY_RECLAIM", "RETENTION", "ENTRY_STILL_ACTIONABLE"),
        "SB03_BASE_EXPANSION": _all(state, "VALID_DAILY_BASE", "DEVELOPING_DAILY_EXPANSION", "PARTICIPATION_SUPPORT", "STRUCTURE_IMPROVES", "ENTRY_STILL_ACTIONABLE"),
        "SB04_CONTROLLED_PULLBACK_ENTRY": _all(state, "VALID_SWING_JOURNEY", "CONTROLLED_RETRACEMENT", "STABILIZATION_AND_RECLAIM", "ENTRY_STILL_ACTIONABLE"),
        "SB05_STRUCTURAL_CONTINUATION": _all(state, "VALID_DAILY_TREND_STRUCTURE", "CURRENT_CONTINUATION_EVENT", "RISK_GEOMETRY_VALID", "REMAINING_ROOM"),
    }
    block_names = ("EOD_FUTURE_LEAKAGE", "ENTRY_WINDOW_PASSED", "LATE_CHASE", "FAILED_RECLAIM_OR_BREAKOUT", "POOR_EFFORT_RESPONSE", "INSUFFICIENT_REMAINING_ROOM", "ILLIQUID", "DATA_INVALID")
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _all(state, "ENTRY_STILL_ACTIONABLE", "INVALIDATION_DEFINED", "REMAINING_SWING_ROOM") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_multibagger(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "MB01_FOUNDATION_EXPANSION": _all(state, "VALID_FOUNDATION_OR_BASE", "PERSISTENT_PARTICIPATION", "EXPANSION_QUALITY", "HIGHER_STRUCTURAL_BASES", "LARGE_REMAINING_ROOM"),
        "MB02_ACCUMULATION_TO_EXPANSION": _all(state, "VALID_ACCUMULATION_EVIDENCE", "PARTICIPATION_PERSISTS", "BREAKOUT_SURVIVES", "CORRECTIONS_CONTROLLED", "LARGE_REMAINING_ROOM"),
        "MB03_MULTI_STAGE_PROGRESS": _all(state, "MULTI_STAGE_HIGHER_PROGRESS", "CORRECTION_SURVIVAL", "STRUCTURAL_RETENTION", "LIQUIDITY_ADEQUATE", "LARGE_REMAINING_ROOM"),
        "MB04_RESILIENT_LONG_JOURNEY": _all(state, "VALID_PRIMARY_JOURNEY", "REPEATED_REACCELERATION_AND_REBASE", "DRAWDOWN_CONTROL", "LARGE_REMAINING_ROOM"),
    }
    block_names = ("HISTORICAL_X2_ALREADY_SPENT_WITHOUT_REMAINING_ROOM", "ONE_CYCLE_PUMP", "PARABOLIC_SPIKE_COLLAPSE", "FAILED_BASE", "BREAKOUT_WITHOUT_PERSISTENCE", "DESTRUCTIVE_DRAWDOWN", "ILLIQUID", "SURVIVORSHIP_OR_HINDSIGHT_ONLY", "DATA_INVALID")
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _all(state, "REFERENCE_BASIS_VALID", "CREDIBLE_REMAINING_X2_PLUS") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_pullback(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "PB01_CONTROLLED_RETRACE_RECLAIM": _all(state, "VALID_PRIMARY_JOURNEY", "CONTROLLED_RETRACEMENT", "THESIS_ALIVE", "SELLING_NOT_DOMINANT", "STABILIZATION", "RECLAIM"),
        "PB02_SUPPORT_RESPONSE_REENTRY": _all(state, "VALID_PRIMARY_JOURNEY", "RETRACE_TO_VALID_SUPPORT", "SUPPORT_RESPONSE", "SELLING_EFFORT_ABSORBED", "REENTRY_GEOMETRY_VALID"),
        "PB03_ACTIVITY_CONTRACTION_REEXPANSION": _all(state, "VALID_PRIMARY_JOURNEY", "PULLBACK_ACTIVITY_CONTRACTS", "STRUCTURE_HOLDS", "RECLAIM", "PARTICIPATION_REEXPANDS"),
        "PB04_VOLATILITY_NORMALIZED_REENTRY": _all(state, "VALID_PRIMARY_JOURNEY", "RETRACEMENT_WITHIN_TICKER_CHARACTER", "STABILIZATION", "FRESH_PROGRESS", "REENTRY_GEOMETRY_VALID"),
    }
    block_names = ("NO_VALID_PRIMARY_JOURNEY", "STRUCTURAL_DAMAGE", "DISTRIBUTION_OR_BREAKDOWN", "FALLING_KNIFE", "EXCESSIVE_RETRACEMENT", "FALSE_RECLAIM", "WEAK_RECOVERY", "SELLING_DOMINANT", "DATA_INVALID")
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _all(state, "PRIMARY_THESIS_ALIVE", "REENTRY_ACTIONABLE") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_overnight(state: Mapping[str, Any]) -> dict[str, Any]:
    paths = {
        "OV01_RETAINED_LATE_SESSION_PROGRESS": _all(state, "LATE_SESSION", "VALID_SWING_JOURNEY", "PROGRESS_RETAINED", "CLOSE_QUALITY_CONTEXT_STRONG", "PARTICIPATION_SUPPORT"),
        "OV02_LATE_REACCELERATION_HOLD": _all(state, "LATE_SESSION", "REACCELERATION", "LIMITED_GIVEBACK", "PARTICIPATION_SUPPORT", "THESIS_DURABLE"),
        "OV03_CONTROLLED_LATE_CONSOLIDATION": _all(state, "LATE_SESSION", "VALID_SWING_JOURNEY", "CONTROLLED_CONSOLIDATION_NEAR_PROGRESS", "NO_DISTRIBUTION", "THESIS_DURABLE"),
        "OV04_RECOVERY_INTO_CLOSE": _all(state, "LATE_SESSION", "PRIOR_INTRADAY_WEAKNESS", "RECLAIM_AND_RETENTION_INTO_CLOSE", "PARTICIPATION_SUPPORT", "THESIS_DURABLE"),
    }
    block_names = ("LARGEST_CHG_ONLY_WITHOUT_DURABILITY", "CLOSE_NEAR_HIGH_ONLY_WITHOUT_CONTEXT", "LATE_EXHAUSTION", "DISTRIBUTION_INTO_CLOSE", "SHARP_REJECTION", "ILLIQUID", "OVERNIGHT_RISK_DOMINATES", "DATA_INVALID")
    blocks = {k: _b(state, k) for k in block_names}
    passed = any(paths.values()) and _all(state, "H1_CARRY_RISK_ACCEPTABLE", "THESIS_DURABLE") and not any(blocks.values())
    return _result(paths, blocks, passed)


def evaluate_all_telegram_families(state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "BUY_READY": evaluate_buy_ready(state),
        "ACCELERATION": evaluate_acceleration(state),
        "ARA_POTENTIAL": evaluate_ara_potential(state),
        "ARA_IMMINENT": evaluate_ara_imminent(state),
        "SWING_BUY": evaluate_swing_buy(state),
        "MULTIBAGGER": evaluate_multibagger(state),
        "PULLBACK": evaluate_pullback(state),
        "OVERNIGHT": evaluate_overnight(state),
    }


def _result(paths: Mapping[str, bool], blocks: Mapping[str, bool], passed: bool) -> dict[str, Any]:
    return {
        "paths": dict(paths),
        "blocks": dict(blocks),
        "matched_paths": [k for k, v in paths.items() if v],
        "blocking_states": [k for k, v in blocks.items() if v],
        "pass": bool(passed),
    }
