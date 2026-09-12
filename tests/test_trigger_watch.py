from a1clean.trigger_watch import evaluate_watch


def _raw():
    return [
        {
            "drive_file_id": "raw-1",
            "name": "Raw Des 02-31-2024.csv",
            "drive_size_bytes": 123,
            "modified_time": "2026-09-12T20:00:00Z",
            "mime_type": "text/csv",
            "md5": "abc",
        }
    ]


def _checkpoint():
    return [
        {
            "file_id": "cp-1",
            "file_name": "DES2024_20241202__CHECKPOINT_CURRENT.json",
            "modified_time": "2026-09-12T20:00:00Z",
            "size": 456,
            "md5": "def",
        }
    ]


def _prior_raw():
    return [
        {
            "drive_file_id": "raw-1",
            "name": "Raw Des 02-31-2024.csv",
            "drive_size_bytes": 123,
            "modified_time": "2026-09-12T20:00:00Z",
            "mime_type": "text/csv",
        }
    ]


def _prior_checkpoint():
    return [
        {
            "file_id": "cp-1",
            "file_name": "DES2024_20241202__CHECKPOINT_CURRENT.json",
            "modified_time": "2026-09-12T20:00:00Z",
        }
    ]


def test_watch_noops_when_raw_and_semantic_checkpoint_metadata_are_current():
    result = evaluate_watch(
        current_raw=_raw(),
        prior_raw=_prior_raw(),
        current_checkpoints=_checkpoint(),
        prior_checkpoints=_prior_checkpoint(),
    )
    assert result["pass"] is True
    assert result["activation_required"] is False
    assert result["status"] == "WATCH_NO_MATERIAL_CHANGE"
    assert result["heavy_local_hashing_performed"] is False
    assert result["canonical_write_performed"] is False


def test_watch_admits_heavy_machine_when_raw_metadata_changes():
    current = _raw()
    current[0]["drive_size_bytes"] = 124
    result = evaluate_watch(
        current_raw=current,
        prior_raw=_prior_raw(),
        current_checkpoints=_checkpoint(),
        prior_checkpoints=_prior_checkpoint(),
    )
    assert result["activation_required"] is True
    assert {row["kind"] for row in result["reasons"]} == {"CANONICAL_RAW_METADATA_CHANGED"}


def test_watch_admits_heavy_machine_when_semantic_checkpoint_advances():
    current = _checkpoint()
    current[0]["modified_time"] = "2026-09-12T20:10:00Z"
    result = evaluate_watch(
        current_raw=_raw(),
        prior_raw=_prior_raw(),
        current_checkpoints=current,
        prior_checkpoints=_prior_checkpoint(),
    )
    assert result["activation_required"] is True
    assert {row["kind"] for row in result["reasons"]} == {"SEMANTIC_CHECKPOINT_METADATA_CHANGED"}


def test_watch_treats_missing_remote_md5_as_activation_hint_not_silent_pass():
    current = _raw()
    current[0]["md5"] = None
    result = evaluate_watch(
        current_raw=current,
        prior_raw=_prior_raw(),
        current_checkpoints=_checkpoint(),
        prior_checkpoints=_prior_checkpoint(),
    )
    assert result["activation_required"] is True
    assert "CANONICAL_RAW_MD5_UNAVAILABLE_HINT" in {row["kind"] for row in result["reasons"]}
