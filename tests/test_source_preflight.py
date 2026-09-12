from pathlib import Path
import hashlib

from a1clean.source_preflight import compare_local_sources


def _md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_source_preflight_uses_drive_as_authority(tmp_path: Path):
    required = b"canonical-source"
    extra = b"local-extra"
    (tmp_path / "Raw Required.csv").write_bytes(required)
    (tmp_path / "Raw Extra.csv").write_bytes(extra)

    drive_files = [
        {
            "id": "drive-required",
            "name": "Raw Required.csv",
            "size": str(len(required)),
            "md5Checksum": _md5(required),
            "modifiedTime": "2026-01-01T00:00:00.000Z",
            "mimeType": "text/csv",
        }
    ]

    report = compare_local_sources(tmp_path, drive_files)
    assert report["pass"] is True
    assert report["canonical_source_count"] == 1
    assert report["extra_local_files"] == ["Raw Extra.csv"]
    assert report["required_sources"][0]["status"] == "PASS_EXACT_MD5"
    assert report["required_sources"][0]["local_sha256"] == _sha256(required)
    assert report["required_sources"][0]["drive_modified_time"] == "2026-01-01T00:00:00.000Z"


def test_source_preflight_holds_on_checksum_mismatch(tmp_path: Path):
    local = b"local"
    remote = b"remote"
    (tmp_path / "Raw Required.csv").write_bytes(local)

    drive_files = [
        {
            "id": "drive-required",
            "name": "Raw Required.csv",
            "size": str(len(local)),
            "md5Checksum": _md5(remote),
        }
    ]

    report = compare_local_sources(tmp_path, drive_files)
    assert report["pass"] is False
    assert report["required_sources"][0]["status"] == "HOLD_CHECKSUM_MISMATCH"


def test_source_preflight_holds_on_duplicate_drive_name(tmp_path: Path):
    data = b"same"
    (tmp_path / "Raw Required.csv").write_bytes(data)
    checksum = _md5(data)
    drive_files = [
        {"id": "a", "name": "Raw Required.csv", "size": str(len(data)), "md5Checksum": checksum},
        {"id": "b", "name": "Raw Required.csv", "size": str(len(data)), "md5Checksum": checksum},
    ]

    report = compare_local_sources(tmp_path, drive_files)
    assert report["pass"] is False
    assert report["duplicate_drive_names"] == ["Raw Required.csv"]
