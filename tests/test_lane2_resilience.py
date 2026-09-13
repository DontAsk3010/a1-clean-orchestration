from __future__ import annotations

from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from a1clean.pattern_discovery.resilience import (
    call_with_retry,
    is_transient_io_error,
    transient_error_status,
)


def _http_error(status: int) -> HttpError:
    resp = SimpleNamespace(status=status, reason="test")
    return HttpError(resp, b'{"error":{"message":"test"}}')


def test_transient_http_classification():
    assert transient_error_status(_http_error(500)) == 500
    assert is_transient_io_error(_http_error(429)) is True
    assert is_transient_io_error(_http_error(503)) is True
    assert is_transient_io_error(_http_error(403)) is False


def test_retry_recovers_without_changing_payload():
    attempts = []
    sleeps = []

    def operation():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise _http_error(500)
        return {"value": 42}

    result = call_with_retry(
        operation,
        operation="unit-test",
        attempts=4,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
        sleep=sleeps.append,
    )
    assert result == {"value": 42}
    assert attempts == [1, 2, 3]
    assert sleeps == [0.0, 0.0]


def test_non_transient_failure_is_not_retried():
    attempts = []

    def operation():
        attempts.append(1)
        raise ValueError("contract bug")

    with pytest.raises(ValueError, match="contract bug"):
        call_with_retry(operation, operation="unit-test", attempts=5, sleep=lambda _: None)
    assert len(attempts) == 1
