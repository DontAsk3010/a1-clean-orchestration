from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
from typing import Any, Callable, Mapping, TypeVar

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from ..source_parity import _download_bytes, _list_children


MACHINE2_CANONICAL_ROOT_FOLDER_ID = "1K4AGWyamGtd5cBCu2odcRzosl4k9DXHA"
MACHINE2_CURRENT_STATE_FOLDER_ID = "1UGEgtftUAasKWF0OHdbDGgYErF60m4zB"
MACHINE2_DATA_PLANE_FOLDER_ID = "1zpQx-CvA5hX6iQfjYI_T7qyTCnFxOJ8y"
MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID = "1oHmkK-D-k7aBZn2nK-7KzMS2tujlvzj5"
MACHINE2_CHECKPOINT_FOLDER_ID = "15L4xQfPxNaulE-uiaGXVYwDdY-2-pBt5"
MACHINE2_GOVERNANCE_FOLDER_ID = "1y77g2dj4zyXqRq17SpKo0oobDQtq0Fyt"

V3_SCIENTIFIC_LINEAGE = "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3"
_GENERATION_SCOPED_FOLDERS = frozenset(
    {
        MACHINE2_CURRENT_STATE_FOLDER_ID,
        MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
        MACHINE2_CHECKPOINT_FOLDER_ID,
    }
)
_EXACT_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_DRIVE_RETRY_DELAYS_SECONDS = (0.0, 2.0, 5.0, 10.0, 20.0)
_DRIVE_AMBIGUOUS_CREATE_RECONCILE_DELAYS_SECONDS = (2.0, 5.0, 10.0)
_T = TypeVar("_T")


def _is_retryable_drive_transport_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, HttpError):
        status = int(getattr(exc.resp, "status", 0) or 0)
        return status in {408, 429, 500, 502, 503, 504}
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "timed out",
            "timeout",
            "connection reset",
            "connection aborted",
            "remote end closed",
            "temporarily unavailable",
        )
    )


def canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current_execution_generation_id() -> str | None:
    """Return the exact execution generation used for durable V3 artifacts.

    CURRENT V3 is a scientific lineage, not a storage generation. A repaired
    exact GitHub HEAD therefore gets its own physical durable-object generation
    so an invalid/partial earlier V3 run cannot be overwritten before governed
    successor/readback proof. The full 40-character commit SHA is retained to
    avoid ambiguous short-SHA identity.
    """

    raw = str(os.environ.get("A1_M2_EXECUTION_GENERATION_ID") or os.environ.get("GITHUB_SHA") or "").strip()
    if not raw:
        return None
    if not _EXACT_GIT_SHA.fullmatch(raw):
        raise RuntimeError("M2_CURRENT_V3_EXECUTION_GENERATION_MUST_BE_EXACT_GIT_SHA")
    return raw.lower()


def physical_name_for_current_execution(
    folder_id: str,
    name: str,
    *,
    generation_id: str | None = None,
) -> str:
    """Map a logical CURRENT V3 artifact name to a non-colliding physical name.

    Only the three Machine-2 CURRENT durable artifact homes are generation
    scoped. RAW/source truth, governance documents and V1/V2 historical objects
    are never renamed or rewritten by this rule.
    """

    if folder_id not in _GENERATION_SCOPED_FOLDERS:
        return name
    prefix = f"{V3_SCIENTIFIC_LINEAGE}__"
    if not name.startswith(prefix):
        return name
    if name.startswith(f"{V3_SCIENTIFIC_LINEAGE}__GEN_"):
        return name

    generation = generation_id if generation_id is not None else current_execution_generation_id()
    if not generation:
        raise RuntimeError("M2_CURRENT_V3_EXECUTION_GENERATION_ID_REQUIRED")
    if not _EXACT_GIT_SHA.fullmatch(generation):
        raise RuntimeError("M2_CURRENT_V3_EXECUTION_GENERATION_MUST_BE_EXACT_GIT_SHA")
    suffix = name[len(prefix) :]
    return f"{V3_SCIENTIFIC_LINEAGE}__GEN_{generation.lower()}__{suffix}"


class Machine2CurrentStore:
    """Durable writer for canonical Machine-2 CURRENT scientific state.

    Source bytes remain in canonical RAW/CURRENT. V3 durable outputs are
    physically generation-scoped by exact Git HEAD while the scientific lineage
    itself remains unchanged. This preserves a non-promotable partial generation
    as RECOVERY_HOLD until a compliant successor is proven and deletion-gated.
    """

    def __init__(self, writer_api):
        self.api = writer_api

    def _transport_call(
        self,
        operation: str,
        call: Callable[[], _T],
        *,
        delays: tuple[float, ...] = _DRIVE_RETRY_DELAYS_SECONDS,
    ) -> _T:
        last_exc: BaseException | None = None
        for attempt, delay in enumerate(delays, start=1):
            if delay:
                time.sleep(delay)
            try:
                return call()
            except BaseException as exc:
                if not _is_retryable_drive_transport_error(exc):
                    raise
                last_exc = exc
                print(
                    "M2_CURRENT_DRIVE_TRANSPORT_RETRY"
                    f"|operation={operation}|attempt={attempt}|max_attempts={len(delays)}"
                    f"|error={type(exc).__name__}",
                    flush=True,
                )
                if attempt == len(delays):
                    raise
        assert last_exc is not None
        raise last_exc

    def _items(self, folder_id: str) -> list[dict[str, Any]]:
        return self._transport_call(
            f"list_children:{folder_id}",
            lambda: _list_children(
                self.api,
                folder_id,
                fields="id,name,mimeType,size,md5Checksum,modifiedTime,parents",
            ),
        )

    def get_optional(self, folder_id: str, name: str) -> dict[str, Any] | None:
        physical_name = physical_name_for_current_execution(folder_id, name)
        matches = [item for item in self._items(folder_id) if item.get("name") == physical_name]
        if not matches:
            return None
        if len(matches) != 1:
            raise RuntimeError(f"M2_CURRENT_FILE_CARDINALITY:{folder_id}:{physical_name}:{len(matches)}")
        return matches[0]

    def read_bytes(self, item: Mapping[str, Any]) -> bytes:
        file_id = str(item["id"])
        return self._transport_call(
            f"read_bytes:{file_id}",
            lambda: _download_bytes(self.api, file_id),
        )

    def read_json_optional(self, folder_id: str, name: str) -> dict[str, Any] | None:
        item = self.get_optional(folder_id, name)
        if item is None:
            return None
        try:
            obj = json.loads(self.read_bytes(item).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"M2_CURRENT_JSON_INVALID:{name}") from exc
        if not isinstance(obj, dict):
            raise RuntimeError(f"M2_CURRENT_JSON_NOT_OBJECT:{name}")
        return obj

    def _write_receipt(
        self,
        *,
        item: Mapping[str, Any],
        physical_name: str,
        logical_name: str,
        data: bytes,
    ) -> dict[str, Any]:
        return {
            "id": str(item["id"]),
            "name": physical_name,
            "logical_name": logical_name,
            "execution_generation_id": current_execution_generation_id()
            if physical_name != logical_name
            else None,
            "size": len(data),
            "sha256": sha256_bytes(data),
            "md5": item.get("md5Checksum"),
            "parents": item.get("parents"),
        }

    def _exact_readback_or_none(
        self,
        *,
        folder_id: str,
        physical_name: str,
        data: bytes,
    ) -> dict[str, Any] | None:
        item = self.get_optional(folder_id, physical_name)
        if item is None:
            return None
        readback = self.read_bytes(item)
        if readback == data and sha256_bytes(readback) == sha256_bytes(data):
            return item
        return None

    def upsert_bytes(self, *, folder_id: str, name: str, data: bytes, mime_type: str) -> dict[str, Any]:
        physical_name = physical_name_for_current_execution(folder_id, name)
        expected = sha256_bytes(data)
        existing = self.get_optional(folder_id, physical_name)

        # An already-committed exact object is a successful idempotent replay.
        if existing is not None:
            readback = self.read_bytes(existing)
            if readback == data and sha256_bytes(readback) == expected:
                return self._write_receipt(
                    item=existing,
                    physical_name=physical_name,
                    logical_name=name,
                    data=data,
                )

        if existing is None:
            # CREATE cannot be blindly retried after a lost response because that
            # can create a duplicate object. Reconcile the exact physical name first.
            try:
                result = self.api.files().create(
                    body={"name": physical_name, "parents": [folder_id]},
                    media_body=MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False),
                    fields="id,name,size,md5Checksum,parents,mimeType",
                    supportsAllDrives=True,
                ).execute()
            except BaseException as exc:
                if not _is_retryable_drive_transport_error(exc):
                    raise
                print(
                    "M2_CURRENT_DRIVE_CREATE_RESPONSE_AMBIGUOUS"
                    f"|name={physical_name}|error={type(exc).__name__}",
                    flush=True,
                )
                for delay in _DRIVE_AMBIGUOUS_CREATE_RECONCILE_DELAYS_SECONDS:
                    time.sleep(delay)
                    committed = self._exact_readback_or_none(
                        folder_id=folder_id,
                        physical_name=physical_name,
                        data=data,
                    )
                    if committed is not None:
                        print(
                            f"M2_CURRENT_DRIVE_CREATE_RECONCILED_PASS|name={physical_name}",
                            flush=True,
                        )
                        return self._write_receipt(
                            item=committed,
                            physical_name=physical_name,
                            logical_name=name,
                            data=data,
                        )
                raise RuntimeError(
                    f"M2_CURRENT_DRIVE_CREATE_AMBIGUOUS_HOLD:{physical_name}"
                ) from exc
        else:
            # UPDATE is safe to retry because every attempt targets the same Drive
            # file id with identical bytes. This is the path used by progressive
            # checkpointing after the initial checkpoint object exists.
            file_id = str(existing["id"])

            def _update_once() -> dict[str, Any]:
                media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
                return self.api.files().update(
                    fileId=file_id,
                    media_body=media,
                    fields="id,name,size,md5Checksum,parents,mimeType",
                    supportsAllDrives=True,
                ).execute()

            result = self._transport_call(
                f"update:{file_id}:{physical_name}",
                _update_once,
            )

        # Readback itself is retry-protected and never causes a second CREATE.
        readback = self.read_bytes({"id": result["id"]})
        actual = sha256_bytes(readback)
        if readback != data or expected != actual:
            raise RuntimeError(f"M2_CURRENT_WRITE_READBACK_MISMATCH:{physical_name}:{expected}:{actual}")
        return self._write_receipt(
            item=result,
            physical_name=physical_name,
            logical_name=name,
            data=data,
        )

    def upsert_json(self, *, folder_id: str, name: str, obj: Any) -> dict[str, Any]:
        return self.upsert_bytes(
            folder_id=folder_id,
            name=name,
            data=canonical_json_bytes(obj),
            mime_type="application/json",
        )

    @property
    def checkpoint_folder_id(self) -> str:
        return MACHINE2_CHECKPOINT_FOLDER_ID

    @property
    def output_folder_id(self) -> str:
        return MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID

    @property
    def current_state_folder_id(self) -> str:
        return MACHINE2_CURRENT_STATE_FOLDER_ID
