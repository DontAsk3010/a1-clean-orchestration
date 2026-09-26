from __future__ import annotations

import json
from pathlib import Path

from a1clean.authority_bootstrap import validate_bootstrap_contract
from a1clean.authority_bootstrap_drive_revision import validate_drive_revision_bindings


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


def test_bootstrap_requires_complete_authority_chain_in_order():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    docs = manifest["authority_documents_in_required_read_order"]
    keys = [row["key"] for row in docs]
    assert keys == [
        "master_handbook",
        "current_execution",
        "sub_master_index",
        "source_capture",
        "behavior_reading",
        "github_automation",
        "formula_research",
        "machine1_dispatch_registry",
        "stable_transition_bridge",
        "chat_transition_protocol",
    ]
    assert all(row["required"] is True for row in docs)
    assert all(str(row.get("drive_revision_id", "")).isdigit() for row in docs)
    assert [row["drive_revision_id"] for row in docs] == ["67", "113", "56", "29", "57", "68", "45", "514", "85", "7"]


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


def test_machine2_remains_independent_full_depth_and_formula_closed():
    manifest = _load("governance/a1-clean-authority-bootstrap-current.json")
    scope = manifest["machine2_scientific_scope"]
    assert scope["independent_full_depth_engine_required"] is True
    assert scope["same_maximum_source_supported_completeness_target_as_machine1"] is True
    assert scope["division_of_labor_as_scientific_design_forbidden"] is True
    assert scope["formula_stage"] == "CLOSED"
