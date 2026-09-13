from __future__ import annotations

import hashlib
import io
import json
from typing import Any, Mapping

from googleapiclient.http import MediaIoBaseUpload

from ..config import (
    LANE2_AUDIT_FOLDER_DRIVE_ID,
    LANE2_AUDIT_FOLDER_NAME,
    LANE2_CONTROL_FOLDER_DRIVE_ID,
    LANE2_CONTROL_FOLDER_NAME,
    LANE2_EVIDENCE_FOLDER_DRIVE_ID,
    LANE2_EVIDENCE_FOLDER_NAME,
    LANE2_ROOT_FOLDER_DRIVE_ID,
    LANE2_ROOT_FOLDER_NAME,
)
from ..source_parity import FOLDER_MIME, _assert_folder, _download_bytes, _list_children
from .contracts import PatternDiscoveryContractError
from .resilience import call_with_retry


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class Lane2DriveStore:
    def __init__(self, writer_api):
        self.api = writer_api
        for folder_id, folder_name in (
            (LANE2_ROOT_FOLDER_DRIVE_ID, LANE2_ROOT_FOLDER_NAME),
            (LANE2_CONTROL_FOLDER_DRIVE_ID, LANE2_CONTROL_FOLDER_NAME),
            (LANE2_EVIDENCE_FOLDER_DRIVE_ID, LANE2_EVIDENCE_FOLDER_NAME),
            (LANE2_AUDIT_FOLDER_DRIVE_ID, LANE2_AUDIT_FOLDER_NAME),
        ):
            call_with_retry(
                lambda folder_id=folder_id, folder_name=folder_name: _assert_folder(
                    self.api, folder_id, folder_name
                ),
                operation=f"drive.assert_folder:{folder_name}",
            )

    @staticmethod
    def _exact(items: list[dict], name: str, *, allow_missing: bool = False) -> dict | None:
        matches = [item for item in items if item.get("name") == name and item.get("mimeType") != FOLDER_MIME]
        if not matches and allow_missing:
            return None
        if len(matches) != 1:
            raise PatternDiscoveryContractError(f"LANE2_FILE_CARDINALITY:{name}:{len(matches)}")
        return matches[0]

    def _folder_items(self, folder_id: str) -> list[dict]:
        return call_with_retry(
            lambda: _list_children(
                self.api,
                folder_id,
                fields="id,name,mimeType,size,md5Checksum,modifiedTime",
            ),
            operation=f"drive.list_children:{folder_id}",
        )

    def get_optional(self, folder_id: str, name: str) -> dict | None:
        return self._exact(self._folder_items(folder_id), name, allow_missing=True)

    def read_bytes(self, item: Mapping[str, Any]) -> bytes:
        file_id = str(item["id"])
        return call_with_retry(
            lambda: _download_bytes(self.api, file_id),
            operation=f"drive.download:{file_id}",
        )

    def read_json_optional(self, folder_id: str, name: str) -> dict[str, Any] | None:
        item = self.get_optional(folder_id, name)
        if item is None:
            return None
        try:
            obj = json.loads(self.read_bytes(item).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PatternDiscoveryContractError(f"LANE2_JSON_INVALID:{name}") from exc
        if not isinstance(obj, dict):
            raise PatternDiscoveryContractError(f"LANE2_JSON_NOT_OBJECT:{name}")
        return obj

    def upsert_bytes(self, *, folder_id: str, name: str, data: bytes, mime_type: str) -> dict[str, Any]:
        # Re-resolve the exact target on every retry. If a create reached Drive but its HTTP
        # response was lost, the next attempt sees that file and updates it instead of creating
        # a duplicate. This keeps the one-name/one-artifact cardinality invariant intact.
        def _upsert_once() -> dict[str, Any]:
            existing = self.get_optional(folder_id, name)
            media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)
            if existing is None:
                request = self.api.files().create(
                    body={"name": name, "parents": [folder_id]},
                    media_body=media,
                    fields="id,name,size,md5Checksum,parents,mimeType",
                    supportsAllDrives=True,
                )
            else:
                request = self.api.files().update(
                    fileId=str(existing["id"]),
                    media_body=media,
                    fields="id,name,size,md5Checksum,parents,mimeType",
                    supportsAllDrives=True,
                )
            return request.execute()

        result = call_with_retry(
            _upsert_once,
            operation=f"drive.upsert:{folder_id}:{name}",
        )
        readback = call_with_retry(
            lambda: _download_bytes(self.api, str(result["id"])),
            operation=f"drive.readback:{result['id']}",
        )
        expected_sha256 = sha256_bytes(data)
        actual_sha256 = sha256_bytes(readback)
        if readback != data or actual_sha256 != expected_sha256:
            raise PatternDiscoveryContractError(
                f"LANE2_UPLOAD_READBACK_MISMATCH:{name}:EXPECTED_SHA256={expected_sha256}:ACTUAL_SHA256={actual_sha256}"
            )
        return {
            "id": str(result["id"]),
            "name": name,
            "size": len(data),
            "sha256": expected_sha256,
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

    def delete_optional(self, folder_id: str, name: str) -> None:
        item = self.get_optional(folder_id, name)
        if item is not None:
            file_id = str(item["id"])
            call_with_retry(
                lambda: self.api.files()
                .delete(fileId=file_id, supportsAllDrives=True)
                .execute(),
                operation=f"drive.delete:{file_id}",
            )

    @property
    def control_folder_id(self) -> str:
        return LANE2_CONTROL_FOLDER_DRIVE_ID

    @property
    def evidence_folder_id(self) -> str:
        return LANE2_EVIDENCE_FOLDER_DRIVE_ID

    @property
    def audit_folder_id(self) -> str:
        return LANE2_AUDIT_FOLDER_DRIVE_ID
