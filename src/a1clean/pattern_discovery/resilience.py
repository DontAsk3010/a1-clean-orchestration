from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from googleapiclient.errors import HttpError

T = TypeVar("T")

TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}


def transient_error_status(exc: BaseException) -> int | None:
    if isinstance(exc, HttpError):
        status = getattr(getattr(exc, "resp", None), "status", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None
    return None


def is_transient_io_error(exc: BaseException) -> bool:
    status = transient_error_status(exc)
    if status in TRANSIENT_HTTP_STATUS:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def call_with_retry(
    fn: Callable[[], T],
    *,
    operation: str,
    attempts: int = 6,
    base_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Retry only transport/transient failures; governance/contract failures pass through.

    The helper is intentionally operational only. It never changes payloads, source identity,
    analytical parameters, date scope, or checkpoint semantics.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except BaseException as exc:
            if not is_transient_io_error(exc) or attempt >= attempts:
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            delay += random.uniform(0.0, min(1.0, delay * 0.15))
            print(
                f"LANE2_TRANSIENT_RETRY operation={operation} attempt={attempt}/{attempts} "
                f"http_status={transient_error_status(exc)} delay_seconds={delay:.2f} "
                f"error={type(exc).__name__}:{exc}"
            )
            sleep(delay)

    raise AssertionError("unreachable")
