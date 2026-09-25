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
from a1clean.canonical_recovery_exact_evidence import load_full_shadow_evidence_exact
from a1clean.config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
)
from a1clean.source_parity import FOLDER_MIME


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


def test_final_shadow_exact_pointer_ignores_orphan_same_named_hold(monkeypatch) -> None:
    import a1clean.canonical_recovery_exact_evidence as exact

    source_name = "Raw Des 02-31-2024.csv"
    stable = {"source_name": source_name, "source_drive_id": "source-drive"}
    root_items = [
        {"id": "final", "name": "FULL_SHADOW_PARITY_FINAL.json", "mimeType": "application/json"},
        {"id": "old-hold-folder", "name": "SRC_0005_Raw_Des_02-31-2024", "mimeType": FOLDER_MIME},
        {"id": "final-pass-folder", "name": "SRC_0005_Raw_Des_02-31-2024", "mimeType": FOLDER_MIME},
    ]
    good_items = [
        {"id": "good-report", "name": "SOURCE_PARITY_REPORT.json", "mimeType": "application/json"},
        {"id": "semantic-manifest", "name": "CANDIDATE__Raw Des 02-31-2024__SEMANTIC_BUNDLES_MANIFEST.json", "mimeType": "application/json"},
        {"id": "market-index", "name": "CANDIDATE__Raw Des 02-31-2024__MARKET_DAY_INDEX.json", "mimeType": "application/json"},
    ]
    listed: list[str] = []

    def fake_list(_api, folder_id: str):
        listed.append(folder_id)
        if folder_id == "root":
            return root_items
        if folder_id == "final-pass-folder":
            return good_items
        if folder_id == "old-hold-folder":
            raise AssertionError("orphan HOLD folder must not be read")
        raise AssertionError(folder_id)

    family = {
        "pass": True,
        "files": [{
            "name": "part.bin",
            "pass": True,
            "candidate_md5": "abc",
            "baseline_md5": "abc",
            "candidate_size": 7,
            "baseline_size": 7,
        }],
    }
    final = {
        "pass": True,
        "completed_source_count": 1,
        "source_summaries": [{
            "pass": True,
            "name": source_name,
            "drive_id": "source-drive",
            "candidate_stable_source": stable,
            "physical_shards": 1,
            "semantic_bundles": 1,
            "evidence_folder_id": "final-pass-folder",
            "source_report_file_id": "good-report",
        }],
    }
    report = {
        "pass": True,
        "source_index": 5,
        "source": {"name": source_name, "drive_id": "source-drive", "size": 10, "drive_md5": "deadbeef"},
        "checks": {
            "source_manifest_stable_fields": {"candidate": stable},
            "physical_shards_exact_md5": family,
            "semantic_bundles_exact_md5": family,
        },
    }

    def fake_download(_api, file_id: str):
        if file_id == "final":
            return final
        if file_id == "good-report":
            return report
        raise AssertionError(file_id)

    monkeypatch.setattr(exact, "_list_children", fake_list)
    monkeypatch.setattr(exact, "_download_json", fake_download)
    evidence = load_full_shadow_evidence_exact(object(), "root")
    assert evidence["source_count"] == 1
    assert evidence["sources"][0]["historical_evidence_folder_id"] == "final-pass-folder"
    assert evidence["sources"][0]["historical_source_report_id"] == "good-report"
    assert "old-hold-folder" not in listed
