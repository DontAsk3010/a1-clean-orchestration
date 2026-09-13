from __future__ import annotations

from pathlib import Path

import pytest

from a1clean.pattern_discovery.self_heal import (
    apply_repair_decision,
    hard_hold_reason,
    redact_secrets,
)


def test_redacts_openai_key_and_bearer_token():
    text = "key=sk-proj-abcdefghijklmnopqrst bearer abcdefghijklmnopqrstuvwxyz"
    redacted = redact_secrets(text)
    assert "sk-proj" not in redacted
    assert "abcdefghijklmnopqrstuvwxyz" not in redacted


def test_governed_identity_mismatch_is_local_hard_hold():
    assert hard_hold_reason("SOURCE_SHA256_MISMATCH:abc") is not None
    assert hard_hold_reason("HTTP 500 Internal Error") is None


def test_retry_only_must_not_modify_files(tmp_path: Path):
    assert apply_repair_decision(
        tmp_path,
        {"action": "RETRY_ONLY", "summary": "transient", "files": []},
    ) == 10


def test_patch_cannot_escape_allowlist(tmp_path: Path):
    with pytest.raises(RuntimeError, match="PATH_NOT_ALLOWED"):
        apply_repair_decision(
            tmp_path,
            {
                "action": "PATCH",
                "summary": "bad",
                "files": [{"path": "plans/lane2/corpus-structural-stage1-v1.json", "content": "{}"}],
            },
        )


def test_patch_replaces_only_allowed_python_file(tmp_path: Path):
    target = tmp_path / "src/a1clean/google_drive.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 1\n", encoding="utf-8")
    code = apply_repair_decision(
        tmp_path,
        {
            "action": "PATCH",
            "summary": "plumbing fix",
            "files": [{"path": "src/a1clean/google_drive.py", "content": "VALUE = 2\n"}],
        },
    )
    assert code == 0
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
