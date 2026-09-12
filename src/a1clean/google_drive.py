from __future__ import annotations

import json
from pathlib import Path
import os

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_READWRITE_SCOPE = "https://www.googleapis.com/auth/drive"


def _credential_path_for_mode(*, read_write: bool) -> str | None:
    if read_write:
        return os.environ.get("A1_DRIVE_WRITER_CREDENTIALS") or os.environ.get(
            "A1_GOOGLE_APPLICATION_CREDENTIALS"
        )
    return os.environ.get("A1_DRIVE_READER_CREDENTIALS") or os.environ.get(
        "A1_GOOGLE_APPLICATION_CREDENTIALS"
    )


def _load_credentials(scopes: list[str], *, read_write: bool):
    credential_path = _credential_path_for_mode(read_write=read_write)
    if credential_path:
        path = Path(credential_path).expanduser().resolve()
        if not path.is_file():
            env_name = (
                "A1_DRIVE_WRITER_CREDENTIALS"
                if read_write
                else "A1_DRIVE_READER_CREDENTIALS"
            )
            raise FileNotFoundError(f"{env_name} credential file not found: {path}")

        payload = json.loads(path.read_text(encoding="utf-8"))
        credential_type = payload.get("type")

        if credential_type == "service_account":
            from google.oauth2 import service_account

            return service_account.Credentials.from_service_account_file(
                str(path), scopes=scopes
            )

        if credential_type == "authorized_user":
            from google.oauth2.credentials import Credentials

            return Credentials.from_authorized_user_file(str(path), scopes=scopes)

        raise ValueError(
            "Unsupported Drive credential JSON type. Expected 'authorized_user' or 'service_account'."
        )

    import google.auth

    creds, _ = google.auth.default(scopes=scopes)
    return creds


def build_drive_api(*, read_write: bool = False):
    from googleapiclient.discovery import build

    scopes = [DRIVE_READWRITE_SCOPE if read_write else DRIVE_READONLY_SCOPE]
    creds = _load_credentials(scopes, read_write=read_write)
    return build("drive", "v3", credentials=creds, cache_discovery=False)
