from __future__ import annotations

import json
from pathlib import Path

import pytest

from a1clean.canonical_recovery import (
    DATA_PLANE_CONTROL_FILES,
    RECOVERY_SCHEMA,
    _compare_expected_file_maps,
    _json_fingerprint,
    _load_request,
    _tree_fingerprint,
)
from a1clean.config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
)


def _request() -> dict:
    return {
        "schema": RECOVERY_SCHEMA,
        "enabled": True,
        "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
        "expected_missing_current_folder_id": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "parity_staging_folder_id": FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        "full_shadow_evidence_folder_id": "evidence",
        "committed_control_bundle_folder_id": "controls",
        "canonical_promotion_allowed": False,
        "raw_write_allowed": False,
        "heavy_behavior_research_allowed": False,
    }


def test_recovery_request_is_prepare_only_and_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_request()), encoding="utf-8")
    loaded = _load_request(path)
    assert loaded["mode"] == "PREPARE_ONLY_NO_CANONICAL_WRITE"
    assert loaded["canonical_promotion_allowed"] is False
    assert loaded["raw_write_allowed"] is False


def test_recovery_request_rejects_canonical_promotion(tmp_path: Path) -> None:
    payload = _request()
    payload["canonical_promotion_allowed"] = True
    path = tmp_path / "request.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="canonical_promotion_allowed"):
        _load_request(path)


def test_exact_file_map_requires_same_names_sizes_and_md5() -> None:
    expected = {"a.bin": {"size": 10, "md5": "abc"}}
    _compare_expected_file_maps(dict(expected), expected, "PHYSICAL")
    with pytest.raises(RuntimeError, match="FILESET_MISMATCH"):
        _compare_expected_file_maps({}, expected, "PHYSICAL")
    with pytest.raises(RuntimeError, match="HASH_MISMATCH"):
        _compare_expected_file_maps({"a.bin": {"size": 11, "md5": "abc"}}, expected, "PHYSICAL")


def test_event_contract_tree_fingerprint_detects_content_change(tmp_path: Path) -> None:
    root = tmp_path / "04_SEMANTIC_EVENT_CONTRACT"
    root.mkdir()
    (root / "contract.json").write_text('{"v":1}', encoding="utf-8")
    first, rows = _tree_fingerprint(root)
    assert rows
    (root / "contract.json").write_text('{"v":2}', encoding="utf-8")
    second, _ = _tree_fingerprint(root)
    assert first != second


def test_json_fingerprint_is_key_order_invariant() -> None:
    assert _json_fingerprint({"a": 1, "b": 2}) == _json_fingerprint({"b": 2, "a": 1})


def test_committed_data_plane_control_set_is_exactly_six() -> None:
    assert DATA_PLANE_CONTROL_FILES == (
        "GLOBAL_DATA_PLANE_MANIFEST.json",
        "GLOBAL_SOURCE_DISCOVERY.json",
        "GLOBAL_SOURCE_COVERAGE_INDEX.json",
        "PERSISTENT_SOURCE_STATE.json",
        "LATEST_DELTA_REFRESH.json",
        "AI_SEMANTIC_DELTA_QUEUE.json",
    )
