from __future__ import annotations

import json
from pathlib import Path

import a1clean.authority_bootstrap_drive_revision as drive_revision_module
from a1clean.authority_bootstrap import validate_bootstrap_contract
from a1clean.authority_bootstrap_drive_revision import (
    apply_drive_revision_policy,
    drive_revision_policy,
    run_authority_bootstrap_drive_revision,
    validate_drive_revision_bindings,
)


ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_bootstrap_contract_is_active_and_fail_closed():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    lock = _load("governance/a1-clean-active-authority-lock.json")
    validate_bootstrap_contract(manifest, lock)
    validate_drive_revision_bindings(manifest)
    assert manifest["full_authority_read_required"] is True
    assert manifest["summary_or_chat_memory_may_not_substitute"] is True
    assert manifest["fail_closed_on_missing_unreadable_or_revision_drift"] is True
    assert manifest["renew_before_source_discovery"] is True
    assert manifest["renew_before_heavy_compute"] is True
    assert manifest["machine2_full_scientific_restart_from_beginning_required"] is True
    assert manifest["machine2_old_pass_skip_forbidden"] is True
    assert manifest["machine2_old_derived_semantic_checkpoint_completion_inherited"] is False
    assert manifest["machine2_owner_hard_lock_full_depth_required"] is True


def test_bootstrap_requires_complete_authority_chain_in_order():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    docs = manifest["authority_documents_in_required_read_order"]
    keys = [row["key"] for row in docs]
    assert keys == [
        "machine2_owner_hard_lock",
        "master_handbook",
        "current_execution",
        "sub_master_index",
        "source_capture",
        "behavior_reading",
        "github_automation",
        "formula_research",
        "machine1_dispatch_registry",
        "canonical_handoff",
        "chat_transition_protocol",
        "stable_transition_bridge",
        "machine2_master_coverage_matrix",
        "storage_handbook",
        "storage_manifest",
    ]
    assert all(row["required"] is True for row in docs)
    assert all(str(row.get("drive_revision_id", "")).isdigit() for row in docs)
    assert [row["drive_revision_id"] for row in docs] == [
        "1",
        "83",
        "158",
        "63",
        "35",
        "64",
        "84",
        "47",
        "587",
        "7",
        "15",
        "91",
        "10",
        "9",
        "18",
    ]


def test_machine2_owner_hard_lock_is_exact_bound_material_authority():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    docs = manifest["authority_documents_in_required_read_order"]
    owner = next(row for row in docs if row["key"] == "machine2_owner_hard_lock")
    assert owner["document_id"] == "1JUIXxdjVD4OsW50RY4r76E_uUp6ukCdUxJTmyJ0w5YM"
    assert owner["drive_revision_id"] == "1"
    assert drive_revision_policy(owner) == "EXACT_BOUND"


def test_storage_manifest_is_live_read_operational_not_exact_revision_blocker():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    docs = manifest["authority_documents_in_required_read_order"]
    storage_manifest = next(row for row in docs if row["key"] == "storage_manifest")
    assert storage_manifest["drive_revision_id"] == "18"
    assert drive_revision_policy(storage_manifest) == "READ_CURRENT_LIVE"


def test_machine1_dispatch_registry_is_live_read_operational_not_exact_revision_blocker():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    docs = manifest["authority_documents_in_required_read_order"]
    registry = next(row for row in docs if row["key"] == "machine1_dispatch_registry")
    master = next(row for row in docs if row["key"] == "master_handbook")

    assert drive_revision_policy(registry) == "READ_CURRENT_LIVE"
    assert drive_revision_policy(master) == "EXACT_BOUND"

    proof = {
        "status": "HOLD",
        "full_authority_read_complete": False,
        "authority_documents": [
            {
                "key": "master_handbook",
                "full_read": True,
                "expected_revision": "83",
                "observed_revision": "83",
            },
            {
                "key": "machine1_dispatch_registry",
                "full_read": True,
                "expected_revision": "587",
                "observed_revision": "999",
            },
        ],
        "repo_state_files": [{"path": "state.json", "full_read": True}],
        "holds": [
            {
                "reason": "AUTHORITY_DOCUMENT_REVISION_DRIFT",
                "key": "machine1_dispatch_registry",
                "expected_revision": "587",
                "observed_revision": "999",
            }
        ],
    }

    reconciled = apply_drive_revision_policy(manifest, proof)
    assert reconciled["status"] == "PASS"
    assert reconciled["full_authority_read_complete"] is True
    assert reconciled["holds"] == []
    assert len(reconciled["accepted_live_revision_drifts"]) == 1
    registry_evidence = next(
        row
        for row in reconciled["authority_documents"]
        if row["key"] == "machine1_dispatch_registry"
    )
    assert registry_evidence["revision_policy"] == "READ_CURRENT_LIVE"
    assert registry_evidence["revision_match_required"] is False
    assert registry_evidence["observed_revision_accepted_as_live_current"] is True


def test_material_authority_revision_drift_still_holds_fail_closed():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    proof = {
        "status": "HOLD",
        "full_authority_read_complete": False,
        "authority_documents": [
            {
                "key": "machine2_owner_hard_lock",
                "full_read": True,
                "expected_revision": "1",
                "observed_revision": "999",
            },
            {
                "key": "machine1_dispatch_registry",
                "full_read": True,
                "expected_revision": "587",
                "observed_revision": "999",
            },
        ],
        "repo_state_files": [{"path": "state.json", "full_read": True}],
        "holds": [
            {
                "reason": "AUTHORITY_DOCUMENT_REVISION_DRIFT",
                "key": "machine2_owner_hard_lock",
                "expected_revision": "1",
                "observed_revision": "999",
            },
            {
                "reason": "AUTHORITY_DOCUMENT_REVISION_DRIFT",
                "key": "machine1_dispatch_registry",
                "expected_revision": "587",
                "observed_revision": "999",
            },
        ],
    }

    reconciled = apply_drive_revision_policy(manifest, proof)
    assert reconciled["status"] == "HOLD"
    assert reconciled["full_authority_read_complete"] is False
    assert reconciled["holds"] == [
        {
            "reason": "AUTHORITY_DOCUMENT_REVISION_DRIFT",
            "key": "machine2_owner_hard_lock",
            "expected_revision": "1",
            "observed_revision": "999",
        }
    ]


def test_registry_read_failure_is_still_a_hard_hold():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    proof = {
        "status": "HOLD",
        "full_authority_read_complete": False,
        "authority_documents": [
            {"key": "master_handbook", "full_read": True},
            {"key": "machine1_dispatch_registry", "full_read": False},
        ],
        "repo_state_files": [{"path": "state.json", "full_read": True}],
        "holds": [
            {
                "reason": "AUTHORITY_DOCUMENT_READ_FAIL",
                "key": "machine1_dispatch_registry",
                "error": "RuntimeError:unreadable",
            }
        ],
    }

    reconciled = apply_drive_revision_policy(manifest, proof)
    assert reconciled["status"] == "HOLD"
    assert reconciled["full_authority_read_complete"] is False
    assert reconciled["holds"][0]["reason"] == "AUTHORITY_DOCUMENT_READ_FAIL"


def test_drive_revision_adapter_calls_current_builder_not_removed_legacy_entrypoint(tmp_path, monkeypatch):
    manifest_path = tmp_path / "bootstrap.json"
    lock_path = tmp_path / "lock.json"
    manifest = {
        "authority_documents_in_required_read_order": [
            {
                "key": "master_handbook",
                "source": "explicit",
                "document_id": "doc-1",
                "revision_id": "authority-revision-label",
                "drive_revision_id": "83",
            }
        ]
    }
    lock = {"documents": {}}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    lock_path.write_text(json.dumps(lock), encoding="utf-8")

    captured = {}

    def fake_current_builder(**kwargs):
        captured.update(kwargs)
        return {
            "schema": "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1",
            "status": "PASS",
            "full_authority_read_complete": True,
            "authority_documents": [{"key": "master_handbook", "full_read": True}],
            "repo_state_files": [],
            "holds": [],
        }

    monkeypatch.setattr(drive_revision_module._base, "build_authority_sync_proof", fake_current_builder)
    assert not hasattr(drive_revision_module._base, "run_authority_bootstrap")

    fake_drive = object()
    result = run_authority_bootstrap_drive_revision(
        manifest_path=manifest_path,
        authority_lock_path=lock_path,
        repo_root=tmp_path,
        drive_api=fake_drive,
    )

    assert captured["manifest"] == manifest
    assert captured["lock"] == lock
    assert captured["drive_api"] is fake_drive
    assert captured["repo_root"] == tmp_path.resolve()
    assert len(captured["manifest_sha256"]) == 64
    assert len(captured["lock_sha256"]) == 64
    assert result["status"] == "PASS"
    assert result["revision_namespace"] == "GOOGLE_DRIVE_CURRENT_REVISION_ID"
    assert result["legacy_docs_revision_tokens_used_for_drive_comparison"] is False


def test_data_contract_has_no_fixed_field_or_source_ceiling_and_preserves_unknowns():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    c = manifest["data_preservation_contract"]
    assert c["dynamic_source_universe_required"] is True
    assert c["fixed_source_count_as_universe_authority_forbidden"] is True
    assert c["fixed_physical_field_whitelist_forbidden"] is True
    assert c["preserve_every_physically_available_authorized_record"] is True
    assert c["preserve_every_physically_available_authorized_field"] is True
    assert c["unknown_or_unmapped_semantics_must_be_preserved"] is True
    assert c["unknown_semantic_state"] == "PHYSICAL_UNKNOWN_SEMANTIC"
    assert c["silent_field_or_row_filtering_forbidden"] is True
    assert c["sampling_for_scientific_scope_forbidden"] is True
    assert c["missing_as_zero_forbidden"] is True


def test_open_ended_family_registry_covers_current_and_future_source_evidence():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    families = set(manifest["required_open_ended_data_families"])
    required = {
        "OHLCV_BAR_HISTORICAL_REPLAY_AT_RICHEST_NATIVE_RESOLUTION",
        "L1_BBO_QUOTE_WHEN_AVAILABLE",
        "TRADE_TICK_TIME_AND_TRADE_AND_SOURCE_DEFINED_AGGRESSOR_WHEN_AVAILABLE",
        "L2_DEPTH_ORDER_BOOK_WHEN_AVAILABLE",
        "TIME_AND_ORDER_QUEUE_REFILL_CANCEL_WHEN_AVAILABLE",
        "BROKER_PARTICIPANT_WHEN_AVAILABLE",
        "FOREIGN_OR_PROVIDER_DEFINED_FLOW_WHEN_AVAILABLE",
        "AUCTION_IEP_IEV_PRICE_LIMIT_FCA_AND_MARKET_MECHANISM_WHEN_AVAILABLE",
        "BENCHMARK_INDEX_SECTOR_AND_MARKET_CONTEXT_WHEN_AVAILABLE",
        "CORPORATE_ACTION_AND_SECURITY_CONTINUITY_WHEN_AVAILABLE",
        "QUALITY_GAP_DUPLICATE_ORDER_RECONNECT_STALE_PARTIAL_AVAILABILITY",
        "FILE_HASH_READBACK_RUN_AND_PROVENANCE",
        "UNKNOWN_FUTURE_PROVIDER_SPECIFIC_PHYSICAL_FIELDS_AND_RECORD_FAMILIES",
    }
    assert required <= families
    assert "PHYSICAL_UNKNOWN_SEMANTIC" in set(manifest["explicit_availability_states"])
    assert "UNKNOWN" in set(manifest["evidence_classes_that_must_not_be_dropped"])


def test_machine2_remains_independent_full_depth_formula_closed_and_restarts_science_from_beginning():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    scope = manifest["machine2_scientific_scope"]
    assert scope["independent_full_depth_engine_required"] is True
    assert scope["same_maximum_source_supported_completeness_target_as_machine1"] is True
    assert scope["division_of_labor_as_scientific_design_forbidden"] is True
    assert scope["full_scientific_restart_from_beginning_required"] is True
    assert scope["old_pass_skip_forbidden"] is True
    assert scope["old_derived_semantic_checkpoint_completion_inherited"] is False
    assert scope["canonical_raw_physical_reuse_after_integrity_proof_only"] is True
    assert scope["programmatic_processing_allowed"] is True
    assert scope["programmatic_semantic_state_detection_allowed_with_full_lineage"] is True
    assert scope["all_actual_source_supported_1m_rows_required_when_available"] is True
    assert scope["missing_minute_as_flat_forbidden"] is True
    assert scope["missing_minute_as_zero_forbidden"] is True
    assert scope["full_owner_hard_lock_domains_required"] is True
    assert scope["current_scientific_lineage"] == "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3"
    assert scope["formula_stage"] == "CLOSED"
