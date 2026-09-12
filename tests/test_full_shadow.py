from a1clean.full_shadow import (
    _candidate_stable_map,
    _final_checks,
    _source_universe_fingerprint,
    _source_universe_rows,
)
from a1clean.parity import STABLE_SOURCE_KEYS


def _source(name: str, drive_id: str, md5: str):
    return {
        "name": name,
        "drive_id": drive_id,
        "drive_size": 10,
        "drive_md5": md5,
        "status": "PASS_EXACT_MD5",
    }


def _stable(name: str, drive_id: str):
    row = {key: None for key in STABLE_SOURCE_KEYS}
    row.update(
        {
            "generation_id": "g",
            "source_name": name,
            "source_drive_id": drive_id,
            "source_size_bytes": 10,
            "source_sha256": "sha-" + drive_id,
            "sampling_used": False,
            "filtering_used": False,
            "behavior_labels_created": False,
        }
    )
    return row


def test_source_universe_fingerprint_is_order_independent_and_count_not_fixed():
    first = {"required_sources": [_source("b.csv", "b", "2"), _source("a.csv", "a", "1")]}
    second = {"required_sources": [_source("a.csv", "a", "1"), _source("b.csv", "b", "2")]}
    assert _source_universe_rows(first) == _source_universe_rows(second)
    assert _source_universe_fingerprint(first) == _source_universe_fingerprint(second)


def test_source_universe_fingerprint_changes_when_canonical_identity_changes():
    first = {"required_sources": [_source("a.csv", "a", "1")]}
    changed = {"required_sources": [_source("a.csv", "a", "9")]}
    assert _source_universe_fingerprint(first) != _source_universe_fingerprint(changed)


def test_final_checks_require_complete_dynamic_membership_and_stable_equality():
    stable_a = _stable("a.csv", "a")
    stable_b = _stable("b.csv", "b")
    preflight = {"required_sources": [_source("a.csv", "a", "1"), _source("b.csv", "b", "2")]}
    checkpoint = {
        "completed_sources": {
            "a": {"pass": True, "candidate_stable_source": stable_a},
            "b": {"pass": True, "candidate_stable_source": stable_b},
        },
        "holds": [],
    }
    baseline = {"sources": [stable_a, stable_b]}
    checks = _final_checks(checkpoint=checkpoint, preflight=preflight, baseline_global=baseline)
    assert all(row["pass"] is True for row in checks.values())
    assert set(_candidate_stable_map(checkpoint)) == {"a", "b"}


def test_final_checks_hold_when_one_dynamic_source_is_missing():
    stable_a = _stable("a.csv", "a")
    stable_b = _stable("b.csv", "b")
    preflight = {"required_sources": [_source("a.csv", "a", "1"), _source("b.csv", "b", "2")]}
    checkpoint = {
        "completed_sources": {
            "a": {"pass": True, "candidate_stable_source": stable_a},
        },
        "holds": [],
    }
    baseline = {"sources": [stable_a, stable_b]}
    checks = _final_checks(checkpoint=checkpoint, preflight=preflight, baseline_global=baseline)
    assert checks["dynamic_source_coverage_exact"]["pass"] is False
    assert checks["all_source_stable_manifests_equal_baseline"]["pass"] is False
