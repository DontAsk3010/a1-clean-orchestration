from __future__ import annotations

import os

import pytest

from a1clean import full_shadow as full_shadow_base
from a1clean.config import FROZEN_IMPL_VERSION
from a1clean.full_shadow import CHECKPOINT_SCHEMA, FULL_SHADOW_GATE, _source_universe_fingerprint, _source_universe_rows
from a1clean.full_shadow_compat import (
    _COMPAT_PREDECESSOR_SHA,
    _COMPAT_RUN_FOLDER,
    _stable_source_with_legacy_impl_fallback,
    _validate_resume_checkpoint_compatible,
)
from a1clean.parity import STABLE_SOURCE_KEYS


def _preflight():
    return {
        "required_sources": [
            {
                "name": "a.csv",
                "drive_id": "a",
                "drive_size": 10,
                "drive_md5": "md5",
                "status": "PASS_EXACT_MD5",
            }
        ]
    }


def _manifest(version):
    row = {key: None for key in STABLE_SOURCE_KEYS}
    row.update(
        {
            "generation_id": "g",
            "source_name": "a.csv",
            "source_drive_id": "a",
            "source_size_bytes": 10,
            "source_sha256": "sha",
            "sampling_used": False,
            "filtering_used": False,
            "behavior_labels_created": False,
            "data_plane_impl_version": version,
        }
    )
    return row


def test_legacy_source_manifest_missing_impl_version_normalizes_only_that_field():
    baseline = _manifest(None)
    normalized = _stable_source_with_legacy_impl_fallback(baseline)
    assert normalized["data_plane_impl_version"] == FROZEN_IMPL_VERSION
    for key in STABLE_SOURCE_KEYS:
        if key != "data_plane_impl_version":
            assert normalized[key] == baseline[key]


def test_non_null_impl_version_is_never_overwritten():
    baseline = _manifest("OTHER")
    normalized = _stable_source_with_legacy_impl_fallback(baseline)
    assert normalized["data_plane_impl_version"] == "OTHER"


def test_fallback_does_not_recurse_when_base_symbol_is_temporarily_patched(monkeypatch):
    baseline = _manifest(None)
    monkeypatch.setattr(
        full_shadow_base,
        "_stable_source",
        _stable_source_with_legacy_impl_fallback,
    )
    normalized = _stable_source_with_legacy_impl_fallback(baseline)
    assert normalized["data_plane_impl_version"] == FROZEN_IMPL_VERSION
    assert normalized["source_name"] == "a.csv"


def _checkpoint(preflight, sha, folder, status="HOLD"):
    return {
        "schema": CHECKPOINT_SCHEMA,
        "gate": FULL_SHADOW_GATE,
        "github_sha": sha,
        "generation_id": "BEHAVIOR_UNIFORM_COLAB_SEMANTIC_GEN_20260910_01",
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": _source_universe_fingerprint(preflight),
        "required_sources": _source_universe_rows(preflight),
        "run_folder_name": folder,
        "status": status,
    }


def test_exact_current_sha_resume_is_allowed(monkeypatch):
    preflight = _preflight()
    monkeypatch.setenv("GITHUB_SHA", "current")
    _validate_resume_checkpoint_compatible(
        _checkpoint(preflight, "current", "any-run"), preflight
    )


def test_only_exact_audited_predecessor_run_may_cross_sha(monkeypatch):
    preflight = _preflight()
    monkeypatch.setenv("GITHUB_SHA", "new")
    _validate_resume_checkpoint_compatible(
        _checkpoint(preflight, _COMPAT_PREDECESSOR_SHA, _COMPAT_RUN_FOLDER), preflight
    )
    with pytest.raises(RuntimeError):
        _validate_resume_checkpoint_compatible(
            _checkpoint(preflight, _COMPAT_PREDECESSOR_SHA, "different-run"), preflight
        )
    with pytest.raises(RuntimeError):
        _validate_resume_checkpoint_compatible(
            _checkpoint(preflight, "unknown-old-sha", _COMPAT_RUN_FOLDER), preflight
        )
