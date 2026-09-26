from __future__ import annotations

import getpass
import hashlib
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

EXPECTED_MACHINE = "PORSCHE-DESIGN"
EXPECTED_USER = "feri-admin"
EXPECTED_PRINCIPAL = "fjulie8satu@gmail.com"
READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
FULL_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
RAW_ID = "1gTyt7CzqlubcdZGjWV_lM9Iw8Zg4ib3e"
RAW_NAME = "02_CURRENT_HISTORICAL_RAW_DATA_UJI"


def fail(code: str) -> None:
    raise RuntimeError(code)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def token_scopes(access_token: str) -> set[str]:
    url = "https://oauth2.googleapis.com/tokeninfo?access_token=" + urllib.parse.quote(access_token, safe="")
    with urllib.request.urlopen(url, timeout=30) as r:
        payload = json.loads(r.read().decode("utf-8"))
    return {s for s in str(payload.get("scope", "")).split() if s}


def main() -> int:
    machine = os.environ.get("COMPUTERNAME", "")
    if machine.upper() != EXPECTED_MACHINE:
        fail(f"A1_READER_REAUTH_WRONG_MACHINE:{machine}")
    user = getpass.getuser()
    if user.lower() != EXPECTED_USER:
        fail(f"A1_READER_REAUTH_WRONG_USER:{user}")

    reader_path = Path(os.environ.get("A1_DRIVE_READER_CREDENTIALS") or rf"C:\Users\{EXPECTED_USER}\a1-drive-auth\reader_credentials.json")
    proof_path = Path(rf"C:\Users\{EXPECTED_USER}\.a1clean\reader-reauth-current.json")
    if not reader_path.is_file():
        fail("A1_READER_REAUTH_CURRENT_READER_MISSING")

    old_hash = sha256(reader_path)
    old = json.loads(reader_path.read_text(encoding="utf-8"))
    if old.get("type") != "authorized_user":
        fail("A1_READER_REAUTH_UNSUPPORTED_CREDENTIAL_TYPE")
    for key in ("client_id", "client_secret", "refresh_token"):
        if not str(old.get(key, "")).strip():
            fail(f"A1_READER_REAUTH_MISSING_{key}")

    token_uri = str(old.get("token_uri") or "https://oauth2.googleapis.com/token")
    if token_uri not in {
        "https://oauth2.googleapis.com/token",
        "https://accounts.google.com/o/oauth2/token",
    }:
        fail("A1_READER_REAUTH_UNEXPECTED_TOKEN_URI")

    # Reuse the exact existing Reader OAuth client. Nothing is created in Google Cloud.
    client_config = {
        "installed": {
            "client_id": old["client_id"],
            "client_secret": old["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": token_uri,
            "redirect_uris": ["http://localhost"],
        }
    }

    print("A1_READER_REAUTH_METHOD=GOOGLE_AUTH_OAUTHLIB_INSTALLED_APP_FLOW")
    print("A1_READER_REAUTH_OAUTH_CLIENT=EXISTING_READER_REUSED")
    print("A1_READER_REAUTH_SCOPE=DRIVE_READONLY_ONLY")
    print("A1_READER_REAUTH_NEW_OAUTH_CLIENT_CREATED=false")
    print("A1_READER_REAUTH_BROWSER_OPENING=TRUE")

    flow = InstalledAppFlow.from_client_config(client_config, scopes=[READONLY_SCOPE])
    creds = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=True,
        authorization_prompt_message="A1 CLEAN Machine 2 Reader authorization opened in your browser.",
        success_message="A1 CLEAN Machine 2 Reader authorization received. You may close this tab.",
        access_type="offline",
        prompt="consent",
    )

    if not creds.token:
        fail("A1_READER_REAUTH_ACCESS_TOKEN_MISSING")
    if not creds.refresh_token:
        fail("A1_READER_REAUTH_REFRESH_TOKEN_MISSING_AFTER_CONSENT")

    scopes = token_scopes(creds.token)
    if READONLY_SCOPE not in scopes:
        fail("A1_READER_REAUTH_READONLY_SCOPE_NOT_GRANTED")
    if FULL_DRIVE_SCOPE in scopes:
        fail("A1_READER_REAUTH_FULL_DRIVE_SCOPE_FORBIDDEN")

    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    about = drive.about().get(fields="user(emailAddress)").execute()
    principal = str((about.get("user") or {}).get("emailAddress") or "").lower()
    if principal != EXPECTED_PRINCIPAL:
        fail("A1_READER_REAUTH_PRINCIPAL_MISMATCH")

    raw = drive.files().get(fileId=RAW_ID, fields="id,name,mimeType", supportsAllDrives=True).execute()
    if raw.get("id") != RAW_ID or raw.get("name") != RAW_NAME or raw.get("mimeType") != "application/vnd.google-apps.folder":
        fail("A1_READER_REAUTH_RAW_IDENTITY_FAIL")

    # Keep an immutable local backup. Rewrite the existing file in place so its ACL remains attached.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = reader_path.with_name(reader_path.name + f".pre-reauth.{stamp}.bak")
    shutil.copy2(reader_path, backup)

    serialized = json.loads(creds.to_json())
    serialized["type"] = "authorized_user"
    serialized["scopes"] = [READONLY_SCOPE]
    reader_path.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
    new_hash = sha256(reader_path)
    if new_hash == old_hash:
        fail("A1_READER_REAUTH_HASH_UNCHANGED_UNEXPECTED")

    proof = {
        "schema": "A1_DRIVE_READER_REAUTH_PROOF_V3",
        "status": "PASS_EXISTING_READER_REAUTHORIZED_READONLY",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "machine": EXPECTED_MACHINE,
        "interactive_user": EXPECTED_USER,
        "method": "GOOGLE_AUTH_OAUTHLIB_INSTALLED_APP_FLOW",
        "existing_oauth_client_reused": True,
        "new_oauth_client_created": False,
        "reader_scope": READONLY_SCOPE,
        "full_drive_scope_granted": False,
        "principal_match": True,
        "raw_identity_read_pass": True,
        "new_refresh_token_proof_pass": True,
        "old_reader_sha256": old_hash,
        "new_reader_sha256": new_hash,
        "backup_created": True,
        "reader_path_unchanged": True,
        "service_binding_change_required": False,
        "drive_write_performed": False,
        "canonical_current_mutation": False,
        "secrets_disclosed": False,
        "next_exact_gate": "RECOVERY_AWARE_DRIVE_GUARDRAIL_READBACK",
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, indent=2), encoding="utf-8")

    print("A1_DRIVE_READER_REAUTH_STATUS=PASS_EXISTING_READER_REAUTHORIZED_READONLY")
    print("EXISTING_OAUTH_CLIENT_REUSED=true")
    print("NEW_OAUTH_CLIENT_CREATED=false")
    print("DRIVE_SCOPE=READONLY_ONLY")
    print("RAW_IDENTITY_READ=PASS")
    print("NEW_REFRESH_TOKEN_PROOF=PASS")
    print("SERVICE_BINDING_CHANGE_REQUIRED=false")
    print("DRIVE_WRITE_PERFORMED=false")
    print("CANONICAL_CURRENT_MUTATION=false")
    print("SECRETS_DISCLOSED=false")
    print(f"PROOF_PATH={proof_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"A1_READER_REAUTH_OFFICIAL_FLOW_FAIL={type(exc).__name__}:{exc}", file=sys.stderr)
        raise
