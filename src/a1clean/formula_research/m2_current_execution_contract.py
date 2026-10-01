from __future__ import annotations

from typing import Any, Mapping


SAFE_ATOMIC_UNITS_PER_SHARD = 1

_REQUIRED_REQUEST_FLAGS = {
    "machine2_full_scientific_restart_from_beginning_required": True,
    "old_pass_may_skip_current_reading_unit": False,
    "old_derived_semantic_checkpoint_completion_inherited": False,
    "date_ticker_record_timestamp_exact_resume_checkpoint_required": True,
    "per_source_only_checkpoint_is_not_sufficient_for_exact_resume": True,
    "strict_governed_chronological_restart_required": True,
    "progressive_current_checkpoint_lineage_must_start_new": True,
    "owner_hard_lock_full_depth_required": True,
    "programmatic_processing_allowed": True,
    "shallow_or_unauditable_processing_allowed": False,
    "full_source_supported_observation_envelope": True,
    "all_source_columns_retrievable_required": True,
    "all_actual_source_supported_1m_rows_required_when_available": True,
    "missing_minute_as_flat_forbidden": True,
    "missing_minute_as_zero_forbidden": True,
    "synthetic_missing_bar_fill_forbidden": True,
    "sparse_ticker_all_actual_rows_required": True,
    "primitive_facts_preserved_before_compression": True,
    "exact_time_known_at_hindsight_separation_required": True,
    "price_path_location_memory_required": True,
    "effort_response_nonresponse_required": True,
    "negative_quiet_failure_contradiction_required": True,
    "attempts_retests_loops_nested_episodes_required": True,
    "state_maturity_persistence_decay_required": True,
    "lead_lag_relationship_graph_required": True,
    "behavior_lifecycle_required": True,
    "behavior_path_required": True,
    "cross_date_continuity_required": True,
    "open_left_right_censoring_required": True,
    "market_sector_cross_sectional_context_required_when_source_supported": True,
    "data_quality_separate_from_market_behavior_required": True,
    "near_twin_counterexample_required_at_applicable_stage": True,
    "base_rate_denominator_readiness_required": True,
    "formation_snapshot_required": True,
    "formation_known_at_vs_hindsight_wall_required": True,
    "availability_unknown_true_zero_discipline_required": True,
    "semantic_label_full_lineage_required": True,
    "dynamic_source_universe_required": True,
    "fixed_source_count_as_universe_authority_forbidden": True,
    "machine1_machine2_division_of_labor_forbidden": True,
    "dual_independent_full_depth_research_engines_required": True,
    "same_maximum_source_supported_completeness_target_required": True,
    "missing_as_zero": False,
    "sampling_used": False,
    "winner_only_filtering_used": False,
    "summary_only_substitution_used": False,
    "no_pass_claim": True,
}

_REQUIRED_SEMANTIC_LABEL_FIELDS = {
    "definition_version",
    "source_parents",
    "exact_time_or_range",
    "known_at_eligibility",
    "derived_parents",
    "reason_features",
    "availability",
    "uncertainty",
    "transition_lineage",
}

_REQUIRED_REF_FIELDS = (
    "selection_position",
    "manifest_index",
    "trading_date",
    "ticker",
    "data_row_count",
    "first_clock_time",
    "last_clock_time",
    "source_row_first",
    "source_row_last",
)


def validate_request_for_current_atomic_restart(request: Mapping[str, Any]) -> None:
    if request.get("enabled") is not True or request.get("restart_authorized") is not True:
        raise RuntimeError("M2_CURRENT_HEAVY_RESTART_NOT_AUTHORIZED")
    for key, expected in _REQUIRED_REQUEST_FLAGS.items():
        if request.get(key) is not expected:
            raise RuntimeError(f"M2_CURRENT_REQUEST_CONTRACT_MISMATCH:{key}")
    if request.get("formula_stage") != "CLOSED":
        raise RuntimeError("M2_CURRENT_FORMULA_STAGE_NOT_CLOSED")
    if request.get("grouping_stage") not in {
        "CLOSED_UNTIL_SEPARATELY_ADMITTED",
        "CLOSED_UNTIL_SEPARATELY_ADMITTED_AFTER_REQUIRED_EVIDENCE_DEPTH",
    }:
        raise RuntimeError("M2_CURRENT_GROUPING_STAGE_NOT_CLOSED")
    spec_path = str(request.get("full_depth_required_domains_spec_path") or "")
    if spec_path != "governance/machine2-full-depth-required-domains-current.json":
        raise RuntimeError("M2_CURRENT_FULL_DEPTH_SPEC_NOT_BOUND")
    label_fields = set(request.get("semantic_label_required_fields") or [])
    missing_label_fields = sorted(_REQUIRED_SEMANTIC_LABEL_FIELDS - label_fields)
    if missing_label_fields:
        raise RuntimeError(f"M2_CURRENT_SEMANTIC_LABEL_LINEAGE_FIELDS_MISSING:{missing_label_fields}")


def validate_exact_unit_ref(ref: Mapping[str, Any] | None, *, label: str) -> None:
    if not isinstance(ref, Mapping):
        raise RuntimeError(f"M2_CURRENT_EXACT_REF_MISSING:{label}")
    missing = [key for key in _REQUIRED_REF_FIELDS if ref.get(key) in (None, "")]
    if missing:
        raise RuntimeError(f"M2_CURRENT_EXACT_REF_FIELDS_MISSING:{label}:{missing}")
    first = int(ref["source_row_first"])
    last = int(ref["source_row_last"])
    count = int(ref["data_row_count"])
    if first < 0 or last < first or count <= 0:
        raise RuntimeError(f"M2_CURRENT_EXACT_REF_RANGE_INVALID:{label}")


def validate_checkpoint_exact_resume(checkpoint: Mapping[str, Any]) -> None:
    status = str(checkpoint.get("status") or "")
    completed = int(checkpoint.get("completed_units_in_current_date") or 0)
    if completed < 0:
        raise RuntimeError("M2_CURRENT_CHECKPOINT_COMPLETED_UNITS_INVALID")

    last_completed = checkpoint.get("last_completed")
    if completed == 0:
        if last_completed is not None:
            raise RuntimeError("M2_CURRENT_CHECKPOINT_LAST_COMPLETED_UNEXPECTED")
    else:
        validate_exact_unit_ref(last_completed, label="LAST_COMPLETED")

    next_ref = checkpoint.get("next_exact_resume_point")
    if status == "DATE_CLOSED":
        if next_ref is not None:
            raise RuntimeError("M2_CURRENT_DATE_CLOSED_HAS_NEXT_RESUME_POINT")
    else:
        validate_exact_unit_ref(next_ref, label="NEXT_EXACT_RESUME_POINT")
        if last_completed is not None:
            if int(next_ref["selection_position"]) != int(last_completed["selection_position"]) + 1:
                raise RuntimeError("M2_CURRENT_RESUME_POSITION_NOT_CONTIGUOUS")


def assert_safe_atomic_units_per_shard(value: int) -> None:
    if int(value) != SAFE_ATOMIC_UNITS_PER_SHARD:
        raise RuntimeError(
            f"M2_CURRENT_SAFE_ATOMIC_CHECKPOINT_REQUIRES_UNITS_PER_SHARD_{SAFE_ATOMIC_UNITS_PER_SHARD}"
        )
