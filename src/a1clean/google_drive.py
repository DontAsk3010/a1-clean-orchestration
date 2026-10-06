from __future__ import annotations

import json
from pathlib import Path
import os

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_READWRITE_SCOPE = "https://www.googleapis.com/auth/drive"
DEFAULT_DRIVE_HTTP_TIMEOUT_SECONDS = 360


def _drive_http_timeout_seconds() -> int:
    raw = str(os.environ.get("A1_DRIVE_HTTP_TIMEOUT_SECONDS") or DEFAULT_DRIVE_HTTP_TIMEOUT_SECONDS).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("A1_DRIVE_HTTP_TIMEOUT_SECONDS_INVALID") from exc
    if value < 30 or value > 900:
        raise RuntimeError("A1_DRIVE_HTTP_TIMEOUT_SECONDS_OUT_OF_RANGE")
    return value


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

        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        credential_type = payload.get("type")

        if credential_type == "service_account":
            from google.oauth2 import service_account

            return service_account.Credentials.from_service_account_info(
                payload, scopes=scopes
            )

        if credential_type == "authorized_user":
            from google.oauth2.credentials import Credentials

            return Credentials.from_authorized_user_info(payload, scopes=scopes)

        raise ValueError(
            "Unsupported Drive credential JSON type. Expected 'authorized_user' or 'service_account'."
        )

    import google.auth

    creds, _ = google.auth.default(scopes=scopes)
    return creds


def build_drive_api(*, read_write: bool = False):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    scopes = [DRIVE_READWRITE_SCOPE if read_write else DRIVE_READONLY_SCOPE]
    creds = _load_credentials(scopes, read_write=read_write)
    http = AuthorizedHttp(
        creds,
        http=httplib2.Http(timeout=_drive_http_timeout_seconds()),
    )
    return build("drive", "v3", http=http, cache_discovery=False)


def build_docs_api():
    """Build a read-only Google Docs API client from the governed Reader credential.

    Authority bootstrap is intentionally Reader-only. It may read the complete
    structured Google Doc and its revision id, but it cannot mutate Drive/Docs.
    """

    from googleapiclient.discovery import build

    creds = _load_credentials([DRIVE_READONLY_SCOPE], read_write=False)
    return build("docs", "v1", credentials=creds, cache_discovery=False)
