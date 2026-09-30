from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Mapping

from googleapiclient.http import MediaIoBaseUpload

from ..source_parity import _download_bytes, _list_children


MACHINE2_CANONICAL_ROOT_FOLDER_ID = "1K4AGWyamGtd5cBCu2odcRzosl4k9DXHA"
MACHINE2_CURRENT_STATE_FOLDER_ID = "1UGEgtftUAasKWF0OHdbDGgYErF60m4zB"
MACHINE2_DATA_PLANE_FOLDER_ID = "1zpQx-CvA5hX6iQfjYI_T7qyTCnFxOJ8y"
MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID = "1oHmkK-D-k7aBZn2nK-7KzMS2tujlvzj5"
MACHINE2_CHECKPOINT_FOLDER_ID = "15L4xQfPxNaulE-uiaGXVYwDdY-2-pBt5"
MACHINE2_GOVERNANCE_FOLDER_ID = "1y77g2dj4zyXqRq17SpKo0oobDQtq0Fyt"


def canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Machine2CurrentStore:
    """Small durable writer for the canonical Machine-2 CURRENT restart lineage.

    Source bytes remain in canonical RAW/CURRENT. This store persists unique
    scientific outputs, exact checkpoints and compact current-state/readback
    controls only. It intentionally does not mirror RAW/source payloads.
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
        matches = [item for item in self._items(folder_id) if item.get("name") == name]
        if not matches:
            return None
        if len(matches) != 1:
            raise RuntimeError(f"M2_CURRENT_FILE_CARDINALITY:{folder_id}:{name}:{len(matches)}")
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
        existing = self.get_optional(folder_id, name)
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
        if existing is None:
            result = self.api.files().create(
                body={"name": name, "parents": [folder_id]},
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
            raise RuntimeError(f"M2_CURRENT_WRITE_READBACK_MISMATCH:{name}:{expected}:{actual}")
        return {
            "id": str(result["id"]),
            "name": name,
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
