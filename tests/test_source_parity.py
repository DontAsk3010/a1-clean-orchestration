import hashlib
from pathlib import Path

from a1clean.parity import STABLE_SOURCE_KEYS
from a1clean.source_parity import (
    _StaticListRequest,
    _compare_hashed_file_family,
    _stable_source,
)


def test_static_list_request_exposes_exact_selected_canonical_metadata_only():
    selected = {
        "id": "keep",
        "name": "a.csv",
        "mimeType": "text/csv",
        "size": "123",
        "md5Checksum": "abc",
    }
    result = _StaticListRequest(selected).execute()
    assert result == {"files": [selected], "nextPageToken": None}


def test_stable_source_uses_existing_parity_contract_keys_only():
    row = {key: f"value:{key}" for key in STABLE_SOURCE_KEYS}
    row["refresh_id"] = "environmental"
    row["source_modified_time"] = "environmental"
    assert _stable_source(row) == {key: row[key] for key in STABLE_SOURCE_KEYS}


def test_hashed_file_family_requires_exact_name_size_and_md5(tmp_path: Path):
    body = b"canonical-bytes"
    candidate_path = tmp_path / "SRC__PHYSICAL_0001.bin"
    candidate_path.write_bytes(body)
    baseline = [
        {
            "name": candidate_path.name,
            "mimeType": "application/octet-stream",
            "size": str(len(body)),
            "md5Checksum": hashlib.md5(body).hexdigest(),
        }
    ]
    report = _compare_hashed_file_family(
        candidate={candidate_path.name: candidate_path},
        baseline_items=baseline,
        prefix="SRC__PHYSICAL_",
        suffix=".bin",
    )
    assert report["pass"] is True
    assert report["candidate_files"] == 1
    assert report["baseline_files"] == 1


def test_hashed_file_family_holds_on_content_mismatch(tmp_path: Path):
    candidate_path = tmp_path / "SRC__SEMANTIC_0001.jsonl"
    candidate_path.write_bytes(b"candidate")
    baseline = [
        {
            "name": candidate_path.name,
            "mimeType": "application/json",
            "size": str(len(b"baseline")),
            "md5Checksum": hashlib.md5(b"baseline").hexdigest(),
        }
    ]
    report = _compare_hashed_file_family(
        candidate={candidate_path.name: candidate_path},
        baseline_items=baseline,
        prefix="SRC__SEMANTIC_",
        suffix=".jsonl",
    )
    assert report["pass"] is False
