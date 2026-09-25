from __future__ import annotations

import pytest

from a1clean.formula_research.source_universe_manifest import build_source_universe_manifest
from a1clean.formula_research.v32_dynamic_prestart import validate_dynamic_prestart


def _authority_sync() -> dict:
    return {
        "schema": "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1",
        "status": "PASS",
        "full_authority_read_complete": True,
        "authority_document_count": 10,
        "repo_state_file_count": 6,
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
