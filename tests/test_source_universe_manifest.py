from __future__ import annotations

from a1clean.formula_research.source_universe_manifest import (
    HISTORICAL_BASELINE_SOURCE_NAMES,
    build_source_universe_manifest,
    manifest_digest_is_valid,
    source_names_from_manifest,
)


def _row(index: int, name: str, first_date: str, last_date: str) -> dict:
    return {
        "source_drive_id": f"drive-{index:02d}",
        "source_name": name,
        "source_sha256": f"sha-{index:02d}",
        "status": "PASS",
        "first_observed_date": first_date,
        "first_observed_time": "09:00:00",
        "last_observed_date": last_date,
        "last_observed_time": "16:15:00",
        "source_data_rows": 100 + index,
        "ticker_day_objects": 10 + index,
        "generation_id": "GEN",
        "data_plane_impl_version": "IMPL",
    }


def _baseline_rows() -> list[dict]:
    envelopes = [
        ("2024-12-02", "2024-12-31"),
        ("2025-01-01", "2025-01-31"),
        ("2025-02-03", "2025-02-28"),
        ("2025-03-03", "2025-03-31"),
        ("2025-04-01", "2025-04-30"),
        ("2025-05-01", "2025-05-30"),
        ("2025-06-02", "2025-06-30"),
        ("2025-07-01", "2025-07-31"),
        ("2025-08-01", "2025-08-29"),
        ("2025-09-01", "2025-09-30"),
        ("2025-10-01", "2025-10-31"),
        ("2025-11-03", "2025-11-29"),
        ("2025-12-01", "2025-12-31"),
        ("2026-01-01", "2026-01-30"),
        ("2026-02-02", "2026-02-27"),
        ("2026-03-02", "2026-03-31"),
        ("2026-04-01", "2026-04-30"),
        ("2026-05-01", "2026-05-29"),
    ]
    return [
        _row(index, name, first_date, last_date)
        for index, (name, (first_date, last_date)) in enumerate(
            zip(HISTORICAL_BASELINE_SOURCE_NAMES, envelopes), start=1
        )
    ]


def _global(rows: list[dict]) -> dict:
    return {
        "generation_id": "GEN",
        "data_plane_impl_version": "IMPL",
        "canonical_source_home_drive_id": "raw-folder",
        "delta_refresh_id": "refresh-1",
        "sources": rows,
    }


def _discovery(rows: list[dict]) -> dict:
    return {
        "files": [
            {
                "drive_file_id": row["source_drive_id"],
                "name": row["source_name"],
                "identity_state": "MATCH",
            }
            for row in rows
        ]
    }


def _build(rows: list[dict], **kwargs) -> dict:
    return build_source_universe_manifest(
        global_manifest=_global(rows),
        discovery=_discovery(rows),
        authority_revision="AUTH-1",
        discovery_time_utc="2026-09-24T10:00:00Z",
        **kwargs,
    )


def test_historical_18_baseline_reproduces_expected_order_without_count_invariant():
    rows = _baseline_rows()
    manifest = _build(rows, required_source_names=HISTORICAL_BASELINE_SOURCE_NAMES)
    assert manifest["status"] == "PASS"
    assert source_names_from_manifest(manifest) == HISTORICAL_BASELINE_SOURCE_NAMES
    assert manifest["source_count"] == 18
    assert manifest["historical_baseline_count_is_not_universe_invariant"] is True
    assert manifest_digest_is_valid(manifest)


def test_new_source_19_is_discovered_and_changes_dynamic_completion_length():
    rows = _baseline_rows()
    rows.append(_row(19, "Raw Jun 01-30-2026.csv", "2026-06-01", "2026-06-30"))
    manifest = _build(rows, required_source_names=HISTORICAL_BASELINE_SOURCE_NAMES)
    names = source_names_from_manifest(manifest)
    assert manifest["status"] == "PASS"
    assert len(names) == 19
    assert names[-1] == "Raw Jun 01-30-2026.csv"


def test_discovery_candidate_cannot_be_silently_ignored_or_auto_promoted():
    rows = _baseline_rows()
    discovery = _discovery(rows)
    discovery["files"].append(
        {"drive_file_id": "drive-19", "name": "Raw Jun 01-30-2026.csv", "identity_state": "MATCH"}
    )
    manifest = build_source_universe_manifest(
        global_manifest=_global(rows),
        discovery=discovery,
        authority_revision="AUTH-1",
        discovery_time_utc="2026-09-24T10:00:00Z",
    )
    assert manifest["status"] == "HOLD"
    assert "UNRECOGNIZED_DISCOVERY_CANDIDATE" in {x["reason"] for x in manifest["holds"]}
    assert "Raw Jun 01-30-2026.csv" not in manifest["source_names_in_order"]


def test_duplicate_source_content_holds():
    rows = _baseline_rows()
    rows[1]["source_sha256"] = rows[0]["source_sha256"]
    manifest = _build(rows)
    assert manifest["status"] == "HOLD"
    assert "DUPLICATE_ACTIVE_SOURCE_CONTENT" in {x["reason"] for x in manifest["holds"]}


def test_overlap_or_conflict_holds():
    rows = _baseline_rows()
    rows[1]["first_observed_date"] = "2024-12-20"
    manifest = _build(rows)
    assert manifest["status"] == "HOLD"
    assert "SOURCE_DATE_OVERLAP_OR_CONFLICT" in {x["reason"] for x in manifest["holds"]}


def test_missing_required_canonical_source_holds():
    rows = _baseline_rows()[1:]
    manifest = _build(rows, required_source_names=HISTORICAL_BASELINE_SOURCE_NAMES)
    assert manifest["status"] == "HOLD"
    assert "REQUIRED_CANONICAL_SOURCE_MISSING" in {x["reason"] for x in manifest["holds"]}


def test_unready_source_is_explicit_and_holds():
    rows = _baseline_rows()
    rows[-1]["source_sha256"] = None
    manifest = _build(rows)
    assert manifest["status"] == "HOLD"
    assert "ACTIVE_SOURCE_NOT_READY" in {x["reason"] for x in manifest["holds"]}
