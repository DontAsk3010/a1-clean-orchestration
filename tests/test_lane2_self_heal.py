from __future__ import annotations

from pathlib import Path

import pytest

import a1clean.pattern_discovery.self_heal as self_heal
from a1clean.pattern_discovery.self_heal import (
    apply_repair_decision,
    decide_repair,
    failure_fingerprint,
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


def test_failure_fingerprint_ignores_retry_noise():
    a = "LANE2_TRANSIENT_RETRY attempt=1/6 delay_seconds=1.23\nRuntimeError: same failure\n"
    b = "LANE2_TRANSIENT_RETRY attempt=5/6 delay_seconds=17.99\nRuntimeError: same failure\n"
    assert failure_fingerprint(a) == failure_fingerprint(b)


def test_identical_persistent_failure_calls_model_only_once(tmp_path: Path, monkeypatch):
    calls = []

    def fake_call(*, log_text, sources):
        calls.append((log_text, sources))
        return {"action": "RETRY_ONLY", "summary": "transient", "files": []}

    monkeypatch.setattr(self_heal, "_call_repair_model", fake_call)
    first = decide_repair(tmp_path, "RuntimeError: identical plumbing failure")
    second = decide_repair(tmp_path, "RuntimeError: identical plumbing failure")

    assert first["action"] == "RETRY_ONLY"
    assert second["action"] == "HARD_HOLD"
    assert "REPEATED_IDENTICAL_FAILURE_NO_SECOND_MODEL_CALL" in second["summary"]
    assert len(calls) == 1


def test_failed_model_transport_is_reserved_and_not_called_again(tmp_path: Path, monkeypatch):
    calls = []

    def fake_call(*, log_text, sources):
        calls.append((log_text, sources))
        raise RuntimeError("OPENAI_REPAIR_TRANSPORT:TimeoutError")

    monkeypatch.setattr(self_heal, "_call_repair_model", fake_call)
    with pytest.raises(RuntimeError, match="OPENAI_REPAIR_TRANSPORT"):
        decide_repair(tmp_path, "RuntimeError: one persistent plumbing failure")

    second = decide_repair(tmp_path, "RuntimeError: one persistent plumbing failure")
    assert second["action"] == "HARD_HOLD"
    assert "REPEATED_IDENTICAL_FAILURE_NO_SECOND_MODEL_CALL:MODEL_CALL_FAILED" in second["summary"]
    assert len(calls) == 1


def test_model_call_budget_is_two_unique_failures(tmp_path: Path, monkeypatch):
    calls = []

    def fake_call(*, log_text, sources):
        calls.append((log_text, sources))
        return {"action": "RETRY_ONLY", "summary": "transient", "files": []}

    monkeypatch.setattr(self_heal, "_call_repair_model", fake_call)
    assert decide_repair(tmp_path, "RuntimeError: failure-one")["action"] == "RETRY_ONLY"
    assert decide_repair(tmp_path, "RuntimeError: failure-two")["action"] == "RETRY_ONLY"
    third = decide_repair(tmp_path, "RuntimeError: failure-three")

    assert third["action"] == "HARD_HOLD"
    assert "SELF_HEAL_MODEL_CALL_BUDGET_EXHAUSTED:2" in third["summary"]
    assert len(calls) == 2


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
