from __future__ import annotations

from a1clean.formula_research.source_universe_manifest import (
    build_source_universe_manifest,
    manifest_digest_is_valid,
)
from a1clean.formula_research.source_universe_semantic_date_reconcile import (
    reconcile_manifest_date_envelopes,
)


def _source(name: str, drive_id: str, digest: str, first_date: str, last_date: str) -> dict:
    return {
        "source_name": name,
        "source_drive_id": drive_id,
        "source_sha256": digest,
        "first_observed_date": first_date,
        "first_observed_time": "09:00:00",
        "last_observed_date": last_date,
        "last_observed_time": "16:00:00",
        "status": "ACCESS_READY_FOR_AI",
        "generation_id": "GEN",
        "data_plane_impl_version": "V2",
    }


def test_semantic_manifest_actual_chronology_reconciles_stale_data_plane_date_envelope_without_hiding_mismatch():
    manifest = build_source_universe_manifest(
        global_manifest={
            "generation_id": "GEN",
            "data_plane_impl_version": "V2",
            "canonical_source_home_drive_id": "HOME",
            "delta_refresh_id": "DELTA",
            "sources": [
                _source("Raw Des 02-31-2024.csv", "drive-dec", "a" * 64, "2024-12-05", "2024-12-30"),
                _source("Raw Jan 01-31-2025.csv", "drive-jan", "b" * 64, "2025-01-02", "2025-01-31"),
            ],
        },
        authority_revision="sha256:test",
        discovery_time_utc="2026-09-30T00:00:00Z",
    )
    assert manifest["status"] == "PASS"
    assert manifest_digest_is_valid(manifest)

    reconciled = reconcile_manifest_date_envelopes(
        manifest,
        {
            "Raw Des 02-31-2024.csv": {
                "source_name": "Raw Des 02-31-2024.csv",
                "source_drive_id": "drive-dec",
                "source_sha256": "a" * 64,
                "first_date": "2024-12-02",
                "first_time": "09:00:00",
                "last_date": "2024-12-30",
                "last_time": "16:01:00",
                "ticker_day_object_count": 16929,
            },
            "Raw Jan 01-31-2025.csv": {
                "source_name": "Raw Jan 01-31-2025.csv",
                "source_drive_id": "drive-jan",
                "source_sha256": "b" * 64,
                "first_date": "2025-01-02",
                "first_time": "09:00:00",
                "last_date": "2025-01-31",
                "last_time": "16:00:00",
                "ticker_day_object_count": 100,
            },
        },
    )

    assert reconciled["status"] == "PASS"
    assert manifest_digest_is_valid(reconciled)
    assert reconciled["sources"][0]["source_name"] == "Raw Des 02-31-2024.csv"
    assert reconciled["sources"][0]["first_date"] == "2024-12-02"
    assert reconciled["sources"][0]["data_plane_date_envelope_original"]["first_date"] == "2024-12-05"
    assert reconciled["sources"][0]["date_envelope_reconciliation_state"] == "MISMATCH_PRESERVED_AND_RECONCILED"
    proof = reconciled["semantic_date_envelope_reconciliation"]
    assert proof["status"] == "PASS"
    assert proof["mismatch_count"] == 1
    assert proof["mismatches"][0]["source_name"] == "Raw Des 02-31-2024.csv"


def test_semantic_reconcile_rejects_identity_drift():
    manifest = build_source_universe_manifest(
        global_manifest={
            "generation_id": "GEN",
            "data_plane_impl_version": "V2",
            "sources": [_source("S.csv", "drive-s", "c" * 64, "2024-12-02", "2024-12-30")],
        },
        authority_revision="sha256:test",
        discovery_time_utc="2026-09-30T00:00:00Z",
    )
    try:
        reconcile_manifest_date_envelopes(
            manifest,
            {
                "S.csv": {
                    "source_name": "S.csv",
                    "source_drive_id": "wrong-drive",
                    "source_sha256": "c" * 64,
                    "first_date": "2024-12-02",
                    "first_time": "09:00:00",
                    "last_date": "2024-12-30",
                    "last_time": "16:00:00",
                    "ticker_day_object_count": 1,
                }
            },
        )
    except RuntimeError as exc:
        assert "SOURCE_UNIVERSE_SEMANTIC_SOURCE_ID_DRIFT" in str(exc)
    else:
        raise AssertionError("identity drift must fail closed")
