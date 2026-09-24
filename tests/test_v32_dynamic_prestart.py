from __future__ import annotations

import pytest

from a1clean.formula_research.source_universe_manifest import build_source_universe_manifest
from a1clean.formula_research.v32_dynamic_prestart import validate_dynamic_prestart


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
