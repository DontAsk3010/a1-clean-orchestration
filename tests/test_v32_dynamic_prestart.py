from __future__ import annotations

import pytest

from a1clean.formula_research.source_universe_manifest import build_source_universe_manifest
from a1clean.formula_research.v32_dynamic_prestart import validate_dynamic_prestart


_CURRENT_FULL_DEPTH_REVALIDATION_KEY = (
    "all_current_master_required_layers_reread_rederive_recompute_or_explicitly_revalidate_from_beginning"
)
_STALE_FULL_DEPTH_REVALIDATION_KEY = (
    "all_current_master_required_layers_reread_rederive_recompute_from_beginning"
)


def _authority_sync() -> dict:
    return {
        "schema": "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1",
        "status": "PASS",
        "full_authority_read_complete": True,
        "authority_document_count": 14,
        "repo_state_file_count": 7,
        "authority_corpus_sha256": "authority-corpus",
        "bootstrap_manifest_sha256": "bootstrap",
        "active_authority_lock_sha256": "lock",
        "data_preservation_contract_sha256": "preservation",
        "required_data_family_registry_sha256": "families",
    }


def _source_manifest() -> dict:
    rows = [
        {
            "source_drive_id": "id-1",
            "source_name": "A.csv",
            "source_sha256": "sha-1",
            "status": "PASS",
            "first_observed_date": "2026-01-01",
            "first_observed_time": "09:00:00",
            "last_observed_date": "2026-01-31",
            "last_observed_time": "16:15:00",
        }
    ]
    return build_source_universe_manifest(
        global_manifest={"sources": rows},
        discovery={"files": [{"drive_file_id": "id-1", "name": "A.csv"}]},
        authority_revision="AUTH",
        discovery_time_utc="2026-09-24T10:00:00Z",
        authority_sync=_authority_sync(),
    )


def _lock() -> dict:
    return {
        "schema": "A1_CLEAN_ACTIVE_AUTHORITY_LOCK_V1",
        "status": "ACTIVE",
        "prestart_completeness_gate_required": True,
        "dynamic_source_universe_required": True,
        "fixed_source_count_as_invariant_forbidden": True,
        "renewable_authority_sync_required": True,
        "formula_stage": "CLOSED",
        "documents": {
            "formula_research": {"document_id": "F", "revision_id": "FR"},
            "source_capture": {"document_id": "S", "revision_id": "SR"},
        },
    }


def _request() -> dict:
    return {
        "schema": "REQ",
        "enabled": False,
        "prestart_completeness_gate_required": True,
        "dynamic_source_universe_required": True,
        "fixed_source_count_as_universe_authority_forbidden": True,
        "renewable_authority_sync_required": True,
        "formula_stage": "CLOSED",
        "formula_research_handbook_document_id": "F",
        "formula_research_handbook_revision_id": "FR",
        "source_capture_handbook_document_id": "S",
        "source_capture_handbook_revision_id": "SR",
    }


def _full_lock() -> dict:
    lock = _lock()
    lock.update(
        {
            "machine2_owner_explicit_full_scientific_restart_from_beginning_required": True,
            "machine2_old_scientific_pass_current_compliance": "NONE_ACCEPTED",
            "machine2_old_scientific_pass_may_skip_current_reading_unit": False,
            "machine2_old_derived_semantic_checkpoint_completion_inherited": False,
            "machine2_canonical_raw_physical_reuse_only_after_current_integrity_proof": True,
            "machine2_scientific_restart_cursor_authority": "EARLIEST_GOVERNED_SOURCE_DATE_TICKER_OBSERVATION_FROM_DYNAMIC_SOURCE_DISCOVERY",
            "machine2_strict_chronological_restart_required": True,
            "machine2_progressive_current_checkpoint_lineage_must_start_new": True,
            "machine2_sunk_cost_exception_allowed": False,
            "machine2_heavy_run_requires_restart_contract_prestart_pass": True,
        }
    )
    lock["documents"]["machine2_master_coverage_matrix"] = {
        "document_id": "MATRIX",
        "revision_id": "MATRIX-REV",
    }
    return lock


def _full_request() -> dict:
    request = _request()
    request.update(
        {
            "schema": "A1_V32_FULL_OBSERVATION_BEHAVIOR_REQUEST_V3",
            "machine2_full_scientific_restart_from_beginning_required": True,
            "old_pass_current_compliance": "NONE_ACCEPTED",
            "old_pass_may_skip_current_reading_unit": False,
            "old_derived_semantic_checkpoint_completion_inherited": False,
            "canonical_raw_physical_reuse_after_current_integrity_proof_only": True,
            "scientific_restart_cursor_authority": "EARLIEST_GOVERNED_SOURCE_DATE_TICKER_OBSERVATION_FROM_DYNAMIC_SOURCE_DISCOVERY",
            "strict_governed_chronological_restart_required": True,
            "progressive_current_checkpoint_lineage_must_start_new": True,
            "date_ticker_record_timestamp_exact_resume_checkpoint_required": True,
            "per_source_only_checkpoint_is_not_sufficient_for_exact_resume": True,
            _CURRENT_FULL_DEPTH_REVALIDATION_KEY: True,
            "sunk_compute_or_old_completion_exception_allowed": False,
            "no_pass_claim": True,
            "machine2_master_coverage_matrix_document_id": "MATRIX",
            "machine2_master_coverage_matrix_revision_id": "MATRIX-REV",
        }
    )
    return request


def test_prestart_validates_dynamic_manifest_without_requiring_fixed_count():
    result = validate_dynamic_prestart(
        request=_request(),
        lock=_lock(),
        source_universe=_source_manifest(),
        require_enabled=False,
    )
    assert result["status"] == "PASS"
    assert result["source_universe_count"] == 1
    assert result["fixed_source_count_invariant_used"] is False
    assert result["authority_sync_status"] == "PASS"
    assert result["authority_corpus_sha256"] == "authority-corpus"


def test_prestart_keeps_disabled_request_on_hold_for_heavy_execution():
    with pytest.raises(RuntimeError, match="PRESTART_REQUEST_DISABLED_HOLD"):
        validate_dynamic_prestart(
            request=_request(),
            lock=_lock(),
            source_universe=_source_manifest(),
            require_enabled=True,
        )


def test_prestart_holds_on_authority_revision_drift():
    request = _request()
    request["formula_research_handbook_revision_id"] = "STALE"
    with pytest.raises(RuntimeError, match="PRESTART_AUTHORITY_REVISION_DRIFT"):
        validate_dynamic_prestart(
            request=request,
            lock=_lock(),
            source_universe=_source_manifest(),
            require_enabled=False,
        )


def test_prestart_holds_if_full_authority_proof_missing():
    manifest = _source_manifest()
    manifest["authority_sync"] = None
    from a1clean.formula_research.source_universe_manifest import _digest
    payload = dict(manifest)
    payload.pop("manifest_digest", None)
    manifest["manifest_digest"] = _digest(payload)
    with pytest.raises(RuntimeError, match="PRESTART_AUTHORITY_SYNC_PROOF_MISSING"):
        validate_dynamic_prestart(
            request=_request(),
            lock=_lock(),
            source_universe=manifest,
            require_enabled=False,
        )


def test_full_observation_prestart_requires_owner_full_restart_contract():
    result = validate_dynamic_prestart(
        request=_full_request(),
        lock=_full_lock(),
        source_universe=_source_manifest(),
        require_enabled=False,
    )
    assert result["status"] == "PASS"
    assert result["machine2_full_scientific_restart_from_beginning_required"] is True
    assert result["old_pass_skip_allowed"] is False


def test_full_observation_prestart_requires_current_v3_full_depth_revalidation_key():
    request = _full_request()
    request.pop(_CURRENT_FULL_DEPTH_REVALIDATION_KEY)
    request[_STALE_FULL_DEPTH_REVALIDATION_KEY] = True
    with pytest.raises(
        RuntimeError,
        match=f"PRESTART_REQUEST_MACHINE2_RESTART_FLAG_FAIL:{_CURRENT_FULL_DEPTH_REVALIDATION_KEY}",
    ):
        validate_dynamic_prestart(
            request=request,
            lock=_full_lock(),
            source_universe=_source_manifest(),
            require_enabled=False,
        )


def test_full_observation_prestart_rejects_old_pass_skip():
    request = _full_request()
    request["old_pass_may_skip_current_reading_unit"] = True
    with pytest.raises(RuntimeError, match="PRESTART_REQUEST_MACHINE2_RESTART_PROHIBITION_FAIL"):
        validate_dynamic_prestart(
            request=request,
            lock=_full_lock(),
            source_universe=_source_manifest(),
            require_enabled=False,
        )


def test_full_observation_prestart_rejects_source_only_checkpoint_contract():
    request = _full_request()
    request["date_ticker_record_timestamp_exact_resume_checkpoint_required"] = False
    with pytest.raises(RuntimeError, match="PRESTART_REQUEST_MACHINE2_RESTART_FLAG_FAIL"):
        validate_dynamic_prestart(
            request=request,
            lock=_full_lock(),
            source_universe=_source_manifest(),
            require_enabled=False,
        )


def test_full_observation_prestart_rejects_coverage_matrix_revision_drift():
    request = _full_request()
    request["machine2_master_coverage_matrix_revision_id"] = "STALE"
    with pytest.raises(RuntimeError, match="PRESTART_MACHINE2_COVERAGE_MATRIX_REVISION_DRIFT"):
        validate_dynamic_prestart(
            request=request,
            lock=_full_lock(),
            source_universe=_source_manifest(),
            require_enabled=False,
        )
