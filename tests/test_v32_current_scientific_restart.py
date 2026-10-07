from __future__ import annotations

import pytest

from a1clean.formula_research.machine2_current_store import (
    MACHINE2_CHECKPOINT_FOLDER_ID,
    MACHINE2_CURRENT_STATE_FOLDER_ID,
    MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
)
from a1clean.formula_research.m2_current_execution_contract import (
    SAFE_ATOMIC_UNITS_PER_SHARD,
    assert_safe_atomic_units_per_shard,
    validate_checkpoint_exact_resume,
    validate_checkpoint_governance_identity,
    validate_request_for_current_atomic_restart,
)
from a1clean.formula_research.v32_current_scientific_restart import (
    CHECKPOINT_NAME,
    LINEAGE,
    PRIOR_LINEAGE,
    build_continuous_current_enrichment,
)


_REQUIRED_AUTHORITY_KEYS = (
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
)


def _bar(i: int, *, close: float, volume: float, value: float, nbss: float, high: float, low: float, timestamp: str | None = None) -> dict:
    return {
        "source_row": 100 + i,
        "timestamp": timestamp or f"2024-12-02 09:{i:02d}:00",
        "source_phase": "REGULAR_SESSION1",
        "regular_behavior_eligible": True,
        "open": close - 1.0,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "trade_value": value,
        "nbss": nbss,
        "haka": value + nbss,
        "haki": value - nbss,
        "haka_haki_status": "SOURCE_BOUND_PROVEN",
        "source_field_count": 12,
        "source_packet_fingerprint": "packet-fp",
    }


def _exact_ref(position: int) -> dict:
    return {
        "selection_position": position,
        "manifest_index": position + 10,
        "trading_date": "2024-12-02",
        "ticker": "AALI",
        "data_row_count": 300,
        "first_clock_time": "09:00:00",
        "last_clock_time": "15:49:00",
        "source_row_first": 1000 + position * 300,
        "source_row_last": 1299 + position * 300,
    }


def _authority_bindings() -> dict:
    return {
        key: {
            "document_id": f"doc-{key}",
            "authority_revision_label": f"authority-revision-{key}",
            "drive_revision_id": "1",
        }
        for key in _REQUIRED_AUTHORITY_KEYS
    }


def _checkpoint_identity() -> dict:
    authority_digest = "a" * 64
    manifest_digest = "b" * 64
    head = "c" * 40
    source_name = "Raw Des 02-31-2024.csv"
    return {
        "lineage": LINEAGE,
        "request_sha256": "d" * 64,
        "software_revision": head,
        "source_universe_manifest_digest": manifest_digest,
        "authority_corpus_sha256": authority_digest,
        "work_id": "workflow-ref",
        "run_id": "12345",
        "repository": "DontAsk3010/a1-clean-orchestration",
        "branch": "fix/v32-dynamic-source-universe-v1",
        "exact_head": head,
        "workflow_identity": {
            "workflow": "Windows Machine2 CURRENT Scientific Restart",
            "workflow_ref": "workflow-ref",
            "workflow_sha": head,
        },
        "schema_versions": {
            "checkpoint": "A1_M2_CURRENT_FULL_DEPTH_CHECKPOINT_V3",
            "scientific_object": "A1_M2_CURRENT_FULL_DEPTH_TICKER_DAY_OBJECT_V3",
            "date_close": "A1_M2_CURRENT_FULL_DEPTH_DATE_CLOSE_V3",
            "owner_full_depth_extension": "V2_EXACT_TIMESTAMP_ALIGNMENT",
        },
        "tests_bound_by_exact_head": True,
        "authority_bindings": _authority_bindings(),
        "authority_sync_readback": {
            "schema": "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1",
            "status": "PASS",
            "full_authority_read_complete": True,
            "authority_document_count": len(_REQUIRED_AUTHORITY_KEYS),
            "repo_state_file_count": 9,
            "authority_corpus_sha256": authority_digest,
            "bootstrap_manifest_sha256": "e" * 64,
            "active_authority_lock_sha256": "f" * 64,
        },
        "source_universe_generation": {
            "generation_ids": ["generation-1"],
            "data_plane_impl_versions": ["impl-1"],
            "source_count": 1,
        },
        "source_identity_by_name": {
            source_name: {
                "source_drive_id": "source-drive-id",
                "source_sha256": "1" * 64,
                "eligibility": "ELIGIBLE_GOVERNED_ACTIVE",
                "readiness": "DATA_PLANE_READY_SEMANTIC_READINESS_EXTERNAL",
                "first_date": "2024-12-02",
                "first_time": "09:00:00",
                "last_date": "2024-12-31",
                "last_time": "15:49:00",
                "schema_source_capability": {
                    "generation_id": "generation-1",
                    "data_plane_impl_version": "impl-1",
                },
            }
        },
        "canonical_artifact_pointers": {
            "checkpoint_folder_id": MACHINE2_CHECKPOINT_FOLDER_ID,
            "semantic_output_folder_id": MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
            "current_state_folder_id": MACHINE2_CURRENT_STATE_FOLDER_ID,
        },
        "checkpoint_write_readback_state": "EXACT_BYTE_READBACK_ENFORCED_OR_WRITE_FAILS",
        "current_gaps_at_prestart": [],
        "hold_or_anomaly_at_prestart": None,
        "temporary_artifacts": [],
        "transport_integrity_proof": {
            "source_universe_manifest_digest": manifest_digest,
            "authority_corpus_sha256": authority_digest,
            "manifest_status": "PASS",
        },
        "current_source": source_name,
    }


def _open_request() -> dict:
    return {
        "enabled": True,
        "restart_authorized": True,
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
        "continue_all_remaining_dates_authorized": True,
        "continuation_authority_scope": "ALL_REMAINING_GOVERNED_TRADING_DATES_IN_DYNAMIC_SOURCE_UNIVERSE",
        "continuation_requires_fresh_authority_and_source_discovery_each_run": True,
        "continuation_requires_exact_next_governed_date": True,
        "continuation_requires_date_close_readback_each_date": True,
        "continuation_single_writer_required": True,
        "continuation_skip_or_parallel_date_forbidden": True,
        "continuation_depth_reduction_forbidden": True,
        "continuation_formula_stage_remains_closed": True,
        "continuation_grouping_stage_remains_closed_until_separately_admitted": True,
        "full_depth_required_domains_spec_path": "governance/machine2-full-depth-required-domains-current.json",
        "semantic_label_required_fields": [
            "definition_version",
            "source_parents",
            "exact_time_or_range",
            "known_at_eligibility",
            "derived_parents",
            "reason_features",
            "availability",
            "uncertainty",
            "transition_lineage",
        ],
        "formula_stage": "CLOSED",
        "grouping_stage": "CLOSED_UNTIL_SEPARATELY_ADMITTED_AFTER_REQUIRED_EVIDENCE_DEPTH",
    }


def test_current_restart_has_new_owner_full_depth_v3_lineage_and_canonical_machine2_home():
    assert PRIOR_LINEAGE == "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V2"
    assert LINEAGE == "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3"
    assert CHECKPOINT_NAME == f"{LINEAGE}__CHECKPOINT_CURRENT.json"
    assert PRIOR_LINEAGE not in CHECKPOINT_NAME
    assert MACHINE2_CHECKPOINT_FOLDER_ID == "15L4xQfPxNaulE-uiaGXVYwDdY-2-pBt5"
    assert MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID == "1oHmkK-D-k7aBZn2nK-7KzMS2tujlvzj5"
    assert MACHINE2_CURRENT_STATE_FOLDER_ID == "1UGEgtftUAasKWF0OHdbDGgYErF60m4zB"


def test_current_atomic_execution_contract_requires_one_unit_per_shard():
    assert SAFE_ATOMIC_UNITS_PER_SHARD == 1
    assert_safe_atomic_units_per_shard(1)
    with pytest.raises(RuntimeError, match="M2_CURRENT_SAFE_ATOMIC_CHECKPOINT_REQUIRES_UNITS_PER_SHARD_1"):
        assert_safe_atomic_units_per_shard(20)


def test_current_atomic_execution_contract_rejects_disabled_request():
    request = _open_request()
    validate_request_for_current_atomic_restart(request)
    request["enabled"] = False
    with pytest.raises(RuntimeError, match="M2_CURRENT_HEAVY_RESTART_NOT_AUTHORIZED"):
        validate_request_for_current_atomic_restart(request)


def test_owner_full_depth_contract_fails_closed_when_required_domain_flag_is_missing():
    request = _open_request()
    request["attempts_retests_loops_nested_episodes_required"] = False
    with pytest.raises(RuntimeError, match="M2_CURRENT_REQUEST_CONTRACT_MISMATCH:attempts_retests_loops_nested_episodes_required"):
        validate_request_for_current_atomic_restart(request)


def test_owner_full_depth_contract_requires_semantic_label_lineage_fields():
    request = _open_request()
    request["semantic_label_required_fields"].remove("transition_lineage")
    with pytest.raises(RuntimeError, match="M2_CURRENT_SEMANTIC_LABEL_LINEAGE_FIELDS_MISSING"):
        validate_request_for_current_atomic_restart(request)


def test_checkpoint_governance_identity_requires_complete_authority_chain():
    checkpoint = _checkpoint_identity()
    validate_checkpoint_governance_identity(checkpoint)
    checkpoint["authority_bindings"].pop("storage_manifest")
    with pytest.raises(RuntimeError, match="M2_CURRENT_CHECKPOINT_AUTHORITY_BINDINGS_MISSING"):
        validate_checkpoint_governance_identity(checkpoint)


def test_checkpoint_governance_identity_rejects_unclosed_prestart_gap():
    checkpoint = _checkpoint_identity()
    checkpoint["current_gaps_at_prestart"] = ["HOLD_ROUTING"]
    with pytest.raises(RuntimeError, match="M2_CURRENT_CHECKPOINT_PRESTART_GAPS_NOT_CLOSED"):
        validate_checkpoint_governance_identity(checkpoint)


def test_exact_resume_checkpoint_requires_contiguous_full_unit_identity():
    checkpoint = {
        **_checkpoint_identity(),
        "status": "IN_PROGRESS",
        "completed_units_in_current_date": 1,
        "last_completed": _exact_ref(0),
        "next_exact_resume_point": _exact_ref(1),
    }
    validate_checkpoint_exact_resume(checkpoint)
    checkpoint["next_exact_resume_point"] = _exact_ref(2)
    with pytest.raises(RuntimeError, match="M2_CURRENT_RESUME_POSITION_NOT_CONTIGUOUS"):
        validate_checkpoint_exact_resume(checkpoint)


def test_continuous_enrichment_preserves_path_effort_response_attempts_and_known_at_uncertainty():
    bars = [
        _bar(0, close=100, volume=10, value=1000, nbss=100, high=101, low=98),
        _bar(1, close=102, volume=20, value=2200, nbss=200, high=103, low=99),
        _bar(2, close=102, volume=30, value=3300, nbss=300, high=104, low=101),
    ]
    result = build_continuous_current_enrichment(bars)
    assert result["derived_observation_count"] == 3
    last = result["derived_observations"][-1]
    assert last["price_geometry"]["fresh_high"] is True
    assert last["price_geometry"]["fresh_high_attempt_number"] == 3
    assert last["price_geometry"]["cumulative_close_path_length"] == 2.0
    assert last["activity_flow"]["volume_delta"] == 10.0
    assert last["activity_flow"]["nbss_delta"] == 100.0
    assert "FLOW_PRESENT_PRICE_NO_RESPONSE_THIS_OBSERVATION" in last["effort_response"]["negative_evidence"]
    assert last["causal_timing"]["known_at"] is None
    assert last["causal_timing"]["known_at_status"] == "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS"
    assert last["multi_timescale_descendants"]["3_actual_bars"]["status"] == "AVAILABLE"
    assert last["multi_timescale_descendants"]["5_actual_bars"]["status"] == "INSUFFICIENT_PRIOR_ACTUAL_BARS"


def test_current_restart_does_not_synthesize_missing_one_minute_rows():
    bars = [
        _bar(0, close=100, volume=10, value=1000, nbss=0, high=100, low=100, timestamp="2024-12-02 09:00:00"),
        _bar(1, close=101, volume=20, value=2000, nbss=0, high=101, low=101, timestamp="2024-12-02 09:05:00"),
    ]
    result = build_continuous_current_enrichment(bars)
    assert result["derived_observation_count"] == 2
    assert result["timestamp_discontinuity_count"] == 1
    gap = result["timestamp_discontinuities"][0]
    assert gap["delta_seconds"] == 300.0
    assert gap["interpretation"] == "SESSION_RECESS_OR_SOURCE_GAP_NOT_INFERRED"


def test_current_restart_does_not_turn_missing_or_unproven_timing_into_zero():
    bars = [_bar(0, close=100, volume=0, value=0, nbss=0, high=100, low=100)]
    result = build_continuous_current_enrichment(bars)
    row = result["derived_observations"][0]
    assert row["causal_timing"]["known_at"] is None
    assert row["causal_timing"]["formation_eligible_at"] is None
    assert row["effort_response"]["nbss_to_price_absolute_efficiency"] is None
    assert row["price_geometry"]["path_efficiency"] is None



def test_owner_continue_all_authority_cannot_be_silently_weakened():
    request = _open_request()
    validate_request_for_current_atomic_restart(request)
    request["continuation_requires_exact_next_governed_date"] = False
    with pytest.raises(RuntimeError, match="M2_CURRENT_REQUEST_CONTRACT_MISMATCH:continuation_requires_exact_next_governed_date"):
        validate_request_for_current_atomic_restart(request)
