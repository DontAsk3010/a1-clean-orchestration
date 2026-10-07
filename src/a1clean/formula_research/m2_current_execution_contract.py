from __future__ import annotations

from typing import Any, Mapping


SAFE_ATOMIC_UNITS_PER_SHARD = 20

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
    "continue_all_remaining_dates_authorized": False,
    "monthly_batch_authorized": True,
    "monthly_batch_auto_dispatch_within_period_only": True,
    "monthly_batch_stop_at_period_boundary": True,
    "monthly_batch_next_period_requires_explicit_dispatch": True,
    "transport_batching_authorized": True,
    "transport_batching_full_scientific_objects_lossless": True,
    "transport_batching_exact_shard_readback_required": True,
    "transport_batching_exact_resume_at_next_unit_required": True,
    "transport_batching_no_evidence_reduction": True,
    "monthly_batch_single_run_sequential_dates_authorized": True,
    "monthly_batch_per_date_exact_readback_required": True,
    "monthly_batch_no_intra_month_workflow_redispatch_required": True,
    "continuation_requires_fresh_authority_and_source_discovery_each_run": True,
    "continuation_requires_exact_next_governed_date": True,
    "continuation_requires_date_close_readback_each_date": True,
    "continuation_single_writer_required": True,
    "continuation_skip_or_parallel_date_forbidden": True,
    "continuation_depth_reduction_forbidden": True,
    "continuation_formula_stage_remains_closed": True,
    "continuation_grouping_stage_remains_closed_until_separately_admitted": True,
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

_REQUIRED_CHECKPOINT_IDENTITY_FIELDS = (
    "lineage",
    "request_sha256",
    "software_revision",
    "source_universe_manifest_digest",
    "authority_corpus_sha256",
    "work_id",
    "run_id",
    "repository",
    "branch",
    "exact_head",
    "workflow_identity",
    "schema_versions",
    "authority_bindings",
    "authority_sync_readback",
    "source_universe_generation",
    "source_identity_by_name",
    "canonical_artifact_pointers",
    "checkpoint_write_readback_state",
    "current_gaps_at_prestart",
    "temporary_artifacts",
    "transport_integrity_proof",
)

_REQUIRED_AUTHORITY_BINDING_KEYS = {
    "machine2_owner_hard_lock",
    "master_handbook",
    "current_execution",
    "sub_master_index",
    "source_capture",
    "behavior_reading",
    "formula_research",
    "github_automation",
    "machine1_dispatch_registry",
    "canonical_handoff",
    "chat_transition_protocol",
    "stable_transition_bridge",
    "machine2_master_coverage_matrix",
    "storage_handbook",
    "storage_manifest",
}


def validate_request_for_current_atomic_restart(request: Mapping[str, Any]) -> None:
    if request.get("enabled") is not True or request.get("restart_authorized") is not True:
        raise RuntimeError("M2_CURRENT_HEAVY_RESTART_NOT_AUTHORIZED")
    for key, expected in _REQUIRED_REQUEST_FLAGS.items():
        if request.get(key) is not expected:
            raise RuntimeError(f"M2_CURRENT_REQUEST_CONTRACT_MISMATCH:{key}")
    if request.get("monthly_batch_mode") != "CALENDAR_MONTH":
        raise RuntimeError("M2_CURRENT_MONTHLY_BATCH_MODE_MISMATCH")
    if request.get("continuation_authority_scope") != "ONE_CALENDAR_MONTH_AT_A_TIME_EXACT_GOVERNED_DATE_ORDER":
        raise RuntimeError("M2_CURRENT_CONTINUATION_AUTHORITY_SCOPE_MISMATCH")
    if int(request.get("transport_units_per_shard") or 0) != SAFE_ATOMIC_UNITS_PER_SHARD:
        raise RuntimeError("M2_CURRENT_TRANSPORT_UNITS_PER_SHARD_MISMATCH")
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


def validate_checkpoint_governance_identity(checkpoint: Mapping[str, Any]) -> None:
    missing = [key for key in _REQUIRED_CHECKPOINT_IDENTITY_FIELDS if key not in checkpoint or checkpoint.get(key) in (None, "")]
    if missing:
        raise RuntimeError(f"M2_CURRENT_CHECKPOINT_GOVERNANCE_FIELDS_MISSING:{missing}")

    if checkpoint.get("exact_head") != checkpoint.get("software_revision"):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_HEAD_SOFTWARE_REVISION_MISMATCH")
    if checkpoint.get("checkpoint_write_readback_state") != "EXACT_BYTE_READBACK_ENFORCED_OR_WRITE_FAILS":
        raise RuntimeError("M2_CURRENT_CHECKPOINT_READBACK_CONTRACT_MISSING")

    bindings = checkpoint.get("authority_bindings")
    if not isinstance(bindings, Mapping):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_AUTHORITY_BINDINGS_NOT_OBJECT")
    missing_bindings = sorted(_REQUIRED_AUTHORITY_BINDING_KEYS - set(bindings))
    if missing_bindings:
        raise RuntimeError(f"M2_CURRENT_CHECKPOINT_AUTHORITY_BINDINGS_MISSING:{missing_bindings}")
    for key in sorted(_REQUIRED_AUTHORITY_BINDING_KEYS):
        row = bindings.get(key)
        if not isinstance(row, Mapping):
            raise RuntimeError(f"M2_CURRENT_CHECKPOINT_AUTHORITY_BINDING_INVALID:{key}")
        for field in ("document_id", "authority_revision_label", "drive_revision_id"):
            if row.get(field) in (None, ""):
                raise RuntimeError(f"M2_CURRENT_CHECKPOINT_AUTHORITY_BINDING_FIELD_MISSING:{key}:{field}")

    sync = checkpoint.get("authority_sync_readback")
    if not isinstance(sync, Mapping) or sync.get("status") != "PASS" or sync.get("full_authority_read_complete") is not True:
        raise RuntimeError("M2_CURRENT_CHECKPOINT_AUTHORITY_SYNC_NOT_PASS")
    if sync.get("authority_corpus_sha256") != checkpoint.get("authority_corpus_sha256"):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_AUTHORITY_CORPUS_DIGEST_MISMATCH")

    source_map = checkpoint.get("source_identity_by_name")
    if not isinstance(source_map, Mapping) or not source_map:
        raise RuntimeError("M2_CURRENT_CHECKPOINT_SOURCE_IDENTITY_MAP_EMPTY")
    current_source = checkpoint.get("current_source")
    if current_source not in (None, "") and current_source not in source_map:
        raise RuntimeError(f"M2_CURRENT_CHECKPOINT_CURRENT_SOURCE_NOT_BOUND:{current_source}")

    transport = checkpoint.get("transport_integrity_proof")
    if not isinstance(transport, Mapping):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_TRANSPORT_PROOF_MISSING")
    if transport.get("source_universe_manifest_digest") != checkpoint.get("source_universe_manifest_digest"):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_SOURCE_MANIFEST_DIGEST_MISMATCH")
    if transport.get("authority_corpus_sha256") != checkpoint.get("authority_corpus_sha256"):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_TRANSPORT_AUTHORITY_DIGEST_MISMATCH")
    if transport.get("manifest_status") != "PASS":
        raise RuntimeError("M2_CURRENT_CHECKPOINT_SOURCE_MANIFEST_NOT_PASS")

    gaps = checkpoint.get("current_gaps_at_prestart")
    if not isinstance(gaps, list):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_GAPS_STATE_NOT_LIST")
    if gaps:
        raise RuntimeError(f"M2_CURRENT_CHECKPOINT_PRESTART_GAPS_NOT_CLOSED:{gaps}")


def validate_checkpoint_exact_resume(checkpoint: Mapping[str, Any]) -> None:
    validate_checkpoint_governance_identity(checkpoint)
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


def validate_output_shard_checkpoint_coverage(
    checkpoint: Mapping[str, Any],
    *,
    max_units_per_shard: int = SAFE_ATOMIC_UNITS_PER_SHARD,
) -> None:
    completed_units = int(checkpoint.get("completed_units_in_current_date") or 0)
    completed_rows = int(checkpoint.get("completed_source_rows_in_current_date") or 0)
    shards = list(checkpoint.get("output_shards") or [])
    if completed_units <= 0 or completed_rows <= 0 or not shards:
        raise RuntimeError("M2_CURRENT_SHARD_COVERAGE_EMPTY")
    expected_first = 0
    packet_total = 0
    row_total = 0
    for ordinal, shard in enumerate(shards, start=1):
        first = int(shard.get("selection_position_first"))
        last = int(shard.get("selection_position_last"))
        packet_count = int(shard.get("packet_count") or 0)
        source_rows = int(shard.get("source_row_count") or 0)
        if first != expected_first:
            raise RuntimeError(f"M2_CURRENT_SHARD_POSITION_GAP:{ordinal}:{expected_first}:{first}")
        if last < first:
            raise RuntimeError(f"M2_CURRENT_SHARD_POSITION_RANGE_INVALID:{ordinal}")
        if packet_count != (last - first + 1):
            raise RuntimeError(f"M2_CURRENT_SHARD_PACKET_COUNT_MISMATCH:{ordinal}")
        if packet_count < 1 or packet_count > int(max_units_per_shard):
            raise RuntimeError(f"M2_CURRENT_SHARD_PACKET_COUNT_UNSAFE:{ordinal}:{packet_count}")
        if source_rows <= 0:
            raise RuntimeError(f"M2_CURRENT_SHARD_SOURCE_ROWS_INVALID:{ordinal}")
        expected_first = last + 1
        packet_total += packet_count
        row_total += source_rows
    if packet_total != completed_units:
        raise RuntimeError("M2_CURRENT_SHARD_COMPLETED_UNIT_RECONCILIATION_FAIL")
    if row_total != completed_rows:
        raise RuntimeError("M2_CURRENT_SHARD_SOURCE_ROW_RECONCILIATION_FAIL")
