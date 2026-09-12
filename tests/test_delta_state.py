from __future__ import annotations

from a1clean.config import FROZEN_GENERATION_ID, FROZEN_IMPL_VERSION
from a1clean.delta_control import build_control_bundle
from a1clean.delta_state import classify_delta_state


def _state(source_id="old", name="Raw A.csv", sha="a" * 64, size=10):
    return {
        "source_drive_id": source_id,
        "source_name": name,
        "source_size_bytes": size,
        "source_modified_time": "2026-01-01T00:00:00.000Z",
        "source_sha256": sha,
        "status": "ACCESS_READY_FOR_AI",
        "physical_shard_count": 1,
        "semantic_bundle_count": 1,
        "source_data_rows": 10,
        "routed_rows": 10,
        "unresolved_routing_rows": 0,
        "unique_trading_dates": 1,
        "unique_tickers": 1,
        "ticker_day_objects": 1,
        "first_observed_date": "2026-01-01",
        "first_observed_time": "09:00:00",
        "last_observed_date": "2026-01-01",
        "last_observed_time": "16:00:00",
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "accepted_at_utc": "2026-01-02T00:00:00+00:00",
    }


def _persistent(*rows):
    return {
        "state_version": 1,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "updated_at_utc": "2026-01-02T00:00:00+00:00",
        "sources": {row["source_drive_id"]: row for row in rows},
    }


def _preflight(*rows):
    required = []
    for row in rows:
        required.append(
            {
                "drive_id": row["source_drive_id"],
                "name": row["source_name"],
                "drive_size": row["source_size_bytes"],
                "drive_modified_time": row.get("source_modified_time"),
                "drive_md5": "md5",
                "local_sha256": row["source_sha256"],
                "local_path": "X:/" + row["source_name"],
                "local_size": row["source_size_bytes"],
                "drive_mime_type": "text/csv",
                "status": "PASS_EXACT_MD5",
            }
        )
    return {
        "pass": True,
        "required_sources": required,
        "canonical_source_count": len(required),
    }


def test_delta_state_classifies_verified_unchanged():
    old = _state()
    result = classify_delta_state(
        preflight=_preflight(old), persistent_state=_persistent(old)
    )
    assert result["pass"] is True
    assert len(result["verified_unchanged"]) == 1
    assert result["new_processed"] == []
    assert result["changed_rebuilt"] == []
    assert result["removed_purged"] == []


def test_delta_state_classifies_new_source():
    old = _state()
    new = _state("new", "Raw B.csv", "b" * 64, 20)
    result = classify_delta_state(
        preflight=_preflight(old, new), persistent_state=_persistent(old)
    )
    assert result["pass"] is True
    assert [row["source_drive_id"] for row in result["new_processed"]] == ["new"]


def test_delta_state_classifies_same_id_changed_content():
    old = _state()
    changed = _state("old", "Raw A.csv", "b" * 64, 11)
    result = classify_delta_state(
        preflight=_preflight(changed), persistent_state=_persistent(old)
    )
    assert result["pass"] is True
    assert len(result["changed_rebuilt"]) == 1
    assert result["changed_rebuilt"][0]["previous_source_drive_id"] == "old"


def test_delta_state_classifies_replacement_same_content():
    old = _state()
    replacement = _state(
        "new", "Raw A.csv", old["source_sha256"], old["source_size_bytes"]
    )
    result = classify_delta_state(
        preflight=_preflight(replacement), persistent_state=_persistent(old)
    )
    assert result["pass"] is True
    assert len(result["replacement_same_content"]) == 1
    assert result["replacement_same_content"][0]["previous_source_drive_id"] == "old"
    assert result["removed_purged"] == []


def test_delta_state_holds_duplicate_current_content():
    a = _state("a", "Raw A.csv", "c" * 64, 10)
    b = _state("b", "Raw B.csv", "c" * 64, 10)
    result = classify_delta_state(
        preflight=_preflight(a, b), persistent_state=_persistent()
    )
    assert result["pass"] is False
    assert any(
        row["reason"] == "DUPLICATE_CURRENT_SOURCE_CONTENT"
        for row in result["holds"]
    )


def test_control_bundle_noop_reclassifies_all_active_sources_unchanged():
    old = _state()
    baseline_global = {
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "runtime_root": "/canonical/current",
        "sources": [
            {
                **old,
                "market_day_index": "/canonical/current/03_MARKET_DAY_INDEX/Raw A__MARKET_DAY_INDEX.json",
                "delta_action": "NEW_PROCESSED",
            }
        ],
    }
    persistent = _persistent(old)
    preflight = _preflight(old)
    classification = classify_delta_state(
        preflight=preflight, persistent_state=persistent
    )
    bundle = build_control_bundle(
        baseline_global=baseline_global,
        baseline_persistent=persistent,
        preflight=preflight,
        classification=classification,
        processed={},
        started_at_utc="start",
        finished_at_utc="finish",
        refresh_id="DELTA_TEST",
    )
    global_source = bundle["GLOBAL_DATA_PLANE_MANIFEST.json"]["sources"][0]
    assert global_source["delta_action"] == "VERIFIED_UNCHANGED"
    assert bundle["PERSISTENT_SOURCE_STATE.json"]["sources"] == persistent["sources"]
    assert bundle["AI_SEMANTIC_DELTA_QUEUE.json"]["full_semantic_sources"] == []
    assert len(bundle["LATEST_DELTA_REFRESH.json"]["verified_unchanged"]) == 1
