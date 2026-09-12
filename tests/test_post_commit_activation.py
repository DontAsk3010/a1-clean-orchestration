from a1clean.automation_activation import (
    ACTIVATION_AUTH_PHRASE,
    ACTIVATE_CANONICAL_IF_CHANGED,
    VERIFY,
)
from a1clean.post_commit import (
    _material_fingerprint,
    _material_projection,
    _snapshot_fingerprint,
)


def test_snapshot_fingerprint_is_order_stable_for_dict_keys():
    left = {"a": 1, "b": {"x": 2, "y": 3}}
    right = {"b": {"y": 3, "x": 2}, "a": 1}
    assert _snapshot_fingerprint(left) == _snapshot_fingerprint(right)


def test_material_fingerprint_ignores_refresh_only_metadata_recursively():
    left = {
        "created_at_utc": "2026-09-12T10:00:00Z",
        "delta_refresh_id": "DELTA_A",
        "sources": [
            {
                "source_drive_id": "S1",
                "source_sha256": "abc",
                "data_state": "VERIFIED_UNCHANGED",
            }
        ],
        "semantic": {
            "updated_at_utc": "2026-09-12T10:00:01Z",
            "runtime_input_fingerprint": "volatile-a",
            "semantic_state": "DATE_OPEN",
            "completed_ticker_context_paths": 130,
        },
    }
    right = {
        "created_at_utc": "2026-09-12T11:00:00Z",
        "delta_refresh_id": "DELTA_B",
        "sources": [
            {
                "source_drive_id": "S1",
                "source_sha256": "abc",
                "data_state": "VERIFIED_UNCHANGED",
            }
        ],
        "semantic": {
            "updated_at_utc": "2026-09-12T11:00:01Z",
            "runtime_input_fingerprint": "volatile-b",
            "semantic_state": "DATE_OPEN",
            "completed_ticker_context_paths": 130,
        },
    }
    assert _material_projection(left) == _material_projection(right)
    assert _material_fingerprint(left) == _material_fingerprint(right)


def test_material_fingerprint_detects_real_semantic_progress():
    before = {
        "updated_at_utc": "2026-09-12T10:00:00Z",
        "sources": {
            "S1": {
                "semantic_state": "DATE_OPEN",
                "completed_ticker_context_paths": 130,
                "remaining_ticker_context_paths": 762,
                "next_exact_resume_point": {"ticker": "BKSL"},
            }
        },
    }
    after = {
        "updated_at_utc": "2026-09-12T11:00:00Z",
        "sources": {
            "S1": {
                "semantic_state": "DATE_OPEN",
                "completed_ticker_context_paths": 131,
                "remaining_ticker_context_paths": 761,
                "next_exact_resume_point": {"ticker": "BMAS"},
            }
        },
    }
    assert _material_fingerprint(before) != _material_fingerprint(after)


def test_material_fingerprint_detects_real_source_change():
    before = {
        "refresh_id": "DELTA_A",
        "sources": [{"source_drive_id": "S1", "source_sha256": "abc"}],
    }
    after = {
        "refresh_id": "DELTA_B",
        "sources": [{"source_drive_id": "S1", "source_sha256": "def"}],
    }
    assert _material_fingerprint(before) != _material_fingerprint(after)


def test_activation_modes_and_authorization_are_explicit():
    assert VERIFY == "VERIFY"
    assert ACTIVATE_CANONICAL_IF_CHANGED == "ACTIVATE_CANONICAL_IF_CHANGED"
    assert ACTIVATION_AUTH_PHRASE == "AUTHORIZE_GOVERNED_AUTOMATION_ACTIVATION"
