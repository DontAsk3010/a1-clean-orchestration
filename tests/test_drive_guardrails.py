from a1clean.drive_guardrails import evaluate_folder_separation
from a1clean.config import (
    CANONICAL_CURRENT_FOLDER_NAME,
    CANONICAL_RAW_FOLDER_NAME,
    PARITY_STAGING_FOLDER_NAME,
)


def _folder(folder_id: str, name: str, *, add: bool, edit: bool) -> dict:
    return {
        "id": folder_id,
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "capabilities": {
            "canAddChildren": add,
            "canEdit": edit,
            "canDelete": False,
            "canTrashChildren": False,
        },
    }


def test_drive_guardrail_accepts_readonly_raw_current_and_writable_staging():
    report = evaluate_folder_separation(
        _folder("raw", CANONICAL_RAW_FOLDER_NAME, add=False, edit=False),
        _folder("current", CANONICAL_CURRENT_FOLDER_NAME, add=False, edit=False),
        _folder("staging", PARITY_STAGING_FOLDER_NAME, add=True, edit=True),
    )
    assert report["pass"] is True


def test_drive_guardrail_holds_if_raw_is_writable():
    report = evaluate_folder_separation(
        _folder("raw", CANONICAL_RAW_FOLDER_NAME, add=True, edit=True),
        _folder("current", CANONICAL_CURRENT_FOLDER_NAME, add=False, edit=False),
        _folder("staging", PARITY_STAGING_FOLDER_NAME, add=True, edit=True),
    )
    assert report["pass"] is False
    assert report["checks"]["raw_read_only"]["pass"] is False


def test_drive_guardrail_holds_if_staging_is_not_writable():
    report = evaluate_folder_separation(
        _folder("raw", CANONICAL_RAW_FOLDER_NAME, add=False, edit=False),
        _folder("current", CANONICAL_CURRENT_FOLDER_NAME, add=False, edit=False),
        _folder("staging", PARITY_STAGING_FOLDER_NAME, add=False, edit=False),
    )
    assert report["pass"] is False
    assert report["checks"]["staging_write_capability"]["pass"] is False


def test_drive_guardrail_holds_on_folder_identity_collision():
    report = evaluate_folder_separation(
        _folder("same", CANONICAL_RAW_FOLDER_NAME, add=False, edit=False),
        _folder("same", CANONICAL_CURRENT_FOLDER_NAME, add=False, edit=False),
        _folder("staging", PARITY_STAGING_FOLDER_NAME, add=True, edit=True),
    )
    assert report["pass"] is False
    assert report["checks"]["folder_ids_distinct"]["pass"] is False
