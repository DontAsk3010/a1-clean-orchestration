from __future__ import annotations

from pathlib import Path
from typing import Any

from . import authority_bootstrap as _base


def _resolve_drive_bound_document(row: dict[str, Any], lock: dict[str, Any]) -> tuple[str, str]:
    """Resolve the document ID from authority, but compare the revision in Drive's own ID namespace.

    The legacy authority `revision_id` fields are Google Docs revision tokens (ANLCK...).
    Reader OAuth currently has Drive API access but not Docs API access. Google Drive revision
    IDs are numeric for these native Docs and are not interchangeable with Docs revision tokens.
    The bootstrap manifest therefore pins the exact current Drive `currentRevisionId` for every
    required authority document. Full text is still exported and hashed before PASS.
    """
    source = str(row.get("source") or "")
    if source == "authority_lock":
        node = dict((lock.get("documents") or {}).get(str(row.get("key") or "")) or {})
        document_id = str(node.get("document_id") or "")
        authority_revision_label = str(node.get("revision_id") or "")
    elif source == "explicit":
        document_id = str(row.get("document_id") or "")
        authority_revision_label = str(row.get("revision_id") or "")
    else:
        raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DOCUMENT_SOURCE_UNKNOWN:{source}")

    drive_revision_id = str(row.get("drive_revision_id") or "")
    if not document_id or not authority_revision_label or not drive_revision_id:
        raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DRIVE_REVISION_BINDING_MISSING:{row.get('key')}")
    return document_id, drive_revision_id


def validate_drive_revision_bindings(manifest: dict[str, Any]) -> None:
    docs = list(manifest.get("authority_documents_in_required_read_order") or [])
    if not docs:
        raise RuntimeError("AUTHORITY_BOOTSTRAP_DOCUMENTS_EMPTY")
    for row in docs:
        value = str(row.get("drive_revision_id") or "")
        if not value or not value.isdigit():
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DRIVE_REVISION_ID_INVALID:{row.get('key')}:{value}")


def run_authority_bootstrap_drive_revision(
    *,
    manifest_path: Path = _base.DEFAULT_MANIFEST,
    authority_lock_path: Path = _base.DEFAULT_LOCK,
    output_path: Path | None = None,
    repo_root: Path = Path("."),
    drive_api: Any | None = None,
) -> dict[str, Any]:
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_drive_revision_bindings(manifest)

    original = _base._resolve_document_binding
    _base._resolve_document_binding = _resolve_drive_bound_document
    try:
        proof = _base.run_authority_bootstrap(
            manifest_path=manifest_path,
            authority_lock_path=authority_lock_path,
            output_path=output_path,
            repo_root=repo_root,
            drive_api=drive_api,
        )
    finally:
        _base._resolve_document_binding = original

    proof["revision_namespace"] = "GOOGLE_DRIVE_CURRENT_REVISION_ID"
    proof["legacy_docs_revision_tokens_used_for_drive_comparison"] = False
    if output_path is not None:
        output_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return proof
