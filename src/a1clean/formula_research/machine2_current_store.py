from __future__ import annotations

import hashlib
import io
import json
import os
import re
from typing import Any, Mapping

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

    def _items(self, folder_id: str) -> list[dict[str, Any]]:
        return _list_children(
            self.api,
            folder_id,
            fields="id,name,mimeType,size,md5Checksum,modifiedTime,parents",
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
        return _download_bytes(self.api, str(item["id"]))

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

    def upsert_bytes(self, *, folder_id: str, name: str, data: bytes, mime_type: str) -> dict[str, Any]:
        physical_name = physical_name_for_current_execution(folder_id, name)
        existing = self.get_optional(folder_id, physical_name)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        if existing is None:
            result = self.api.files().create(
                body={"name": physical_name, "parents": [folder_id]},
                media_body=media,
                fields="id,name,size,md5Checksum,parents,mimeType",
                supportsAllDrives=True,
            ).execute()
        else:
            result = self.api.files().update(
                fileId=str(existing["id"]),
                media_body=media,
                fields="id,name,size,md5Checksum,parents,mimeType",
                supportsAllDrives=True,
            ).execute()
        readback = self.read_bytes({"id": result["id"]})
        expected = sha256_bytes(data)
        actual = sha256_bytes(readback)
        if readback != data or expected != actual:
            raise RuntimeError(f"M2_CURRENT_WRITE_READBACK_MISMATCH:{physical_name}:{expected}:{actual}")
        return {
            "id": str(result["id"]),
            "name": physical_name,
            "logical_name": name,
            "execution_generation_id": current_execution_generation_id()
            if physical_name != name
            else None,
            "size": len(data),
            "sha256": expected,
            "md5": result.get("md5Checksum"),
            "parents": result.get("parents"),
        }

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
