from __future__ import annotations

import pytest

from a1clean.canonical_promotion import (
    CANONICAL,
    PREPARE,
    _assert_shadow_result,
    _fingerprint_rows,
    _promotion_plan,
    _target_prefix_match,
)


def _shadow():
    return {
        "pass": True,
        "status": "SHADOW_COMMIT_READY",
        "semantic_runtime_status": "AVAILABLE",
        "semantic_runtime_holds": [],
        "control_bundle": {"pass": True, "folder_id": "control-folder"},
        "classification": {"holds": []},
        "github_sha": "a" * 40,
        "run_folder_id": "shadow-folder",
        "run_key": "run-key",
        "semantic_input_fingerprint": "semantic-fingerprint",
        "canonical_commit_operations": {
            "purge_before_upsert": [],
            "upsert_processed_sources": [],
            "commit_order": ["RECONCILE_DATA_PLANE_RUNTIME", "ATOMIC_SEMANTIC_LEDGER_AND_WORK_QUEUE_COMMIT"],
        },
    }


def test_shadow_result_guard_requires_real_ready_machine_state():
    _assert_shadow_result(_shadow())
    bad = _shadow()
    bad["semantic_runtime_holds"] = [{"reason": "x"}]
    with pytest.raises(RuntimeError, match="SEMANTIC_RUNTIME_HOLD"):
        _assert_shadow_result(bad)


def test_prepare_plan_never_claims_canonical_write_request():
    plan = _promotion_plan(_shadow(), mode=PREPARE, transaction_folder_id="tx")
    assert plan["canonical_write_requested"] is False
    assert plan["raw_write_authorized"] is False
    assert plan["transaction_folder_id"] == "tx"


def test_canonical_plan_requires_explicit_authorization_path():
    plan = _promotion_plan(_shadow(), mode=CANONICAL, transaction_folder_id="tx")
    assert plan["canonical_write_requested"] is True
    assert plan["authorization_phrase_required"] is True
    assert plan["raw_write_authorized"] is False


def test_source_family_matching_is_source_scoped():
    source = "Raw Des 02-31-2024.csv"
    assert _target_prefix_match(
        "Raw Des 02-31-2024__DATA_PLANE_MANIFEST.json",
        source_name=source,
        logical_folder="00_MANIFESTS",
    )
    assert _target_prefix_match(
        "Raw Des 02-31-2024__PHYSICAL_0001.bin",
        source_name=source,
        logical_folder="01_ACCESS_SHARDS",
    )
    assert not _target_prefix_match(
        "Raw Des 01-31-2025__PHYSICAL_0001.bin",
        source_name=source,
        logical_folder="01_ACCESS_SHARDS",
    )


def test_fingerprint_rows_ignores_drive_ids_and_orders_stably():
    rows = [
        {"id": "b", "name": "z", "size": "2", "md5Checksum": "bb"},
        {"id": "a", "name": "a", "size": "1", "md5Checksum": "aa"},
    ]
    assert _fingerprint_rows(rows) == [
        {"name": "a", "size": 1, "md5": "aa"},
        {"name": "z", "size": 2, "md5": "bb"},
    ]
