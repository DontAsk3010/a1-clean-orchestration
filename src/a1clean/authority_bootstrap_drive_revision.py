from __future__ import annotations

from pathlib import Path
from typing import Any

from . import authority_bootstrap as _base


LIVE_CURRENT_OPERATIONAL_KEYS = frozenset(
    {
        "machine1_dispatch_registry",
    }
)


def drive_revision_policy(row: dict[str, Any]) -> str:
    """Return how Drive revision drift is interpreted for one authority document.

    Scientific/method authorities remain exact-bound and fail closed on revision drift.
    The Machine-1 Dispatch Registry is a volatile operational coordination document:
    Machine 2 must still fresh-read it in full and prove its identity/readability, but
    a newer numeric Drive revision alone is not a scientific dependency and therefore
    must not stop Machine 2.
    """
    key = str(row.get("key") or "")
    return "READ_CURRENT_LIVE" if key in LIVE_CURRENT_OPERATIONAL_KEYS else "EXACT_BOUND"


def _resolve_drive_bound_document(row: dict[str, Any], lock: dict[str, Any]) -> tuple[str, str]:
    """Resolve the document ID from authority, but compare the revision in Drive's own ID namespace.

    The legacy authority `revision_id` fields are Google Docs revision tokens (ANLCK...).
    Reader OAuth currently has Drive API access but not Docs API access. Google Drive revision
    IDs are numeric for these native Docs and are not interchangeable with Docs revision tokens.
    The bootstrap manifest therefore pins the exact current Drive `currentRevisionId` for every
    exact-bound authority document. Full text is still exported and hashed before PASS.

    For READ_CURRENT_LIVE operational documents the numeric value remains a provenance anchor;
    any newer observed Drive revision is accepted only after the same full native export succeeds.
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
        policy = drive_revision_policy(row)
        if policy not in {"EXACT_BOUND", "READ_CURRENT_LIVE"}:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DRIVE_REVISION_POLICY_INVALID:{row.get('key')}:{policy}")


def apply_drive_revision_policy(manifest: dict[str, Any], proof: dict[str, Any]) -> dict[str, Any]:
    """Apply dependency-aware revision semantics after the full authority read.

    This never converts a missing/unreadable/wrong authority document into PASS. It only
    prevents numeric revision churn in explicitly operational live-current documents from
    becoming a false Machine-2 scientific HOLD.
    """
    policy_by_key = {
        str(row.get("key") or ""): drive_revision_policy(row)
        for row in manifest.get("authority_documents_in_required_read_order") or []
    }
    live_keys = {
        key for key, policy in policy_by_key.items() if policy == "READ_CURRENT_LIVE"
    }

    remaining_holds: list[dict[str, Any]] = []
    accepted_live_revision_drifts: list[dict[str, Any]] = []
    for hold in list(proof.get("holds") or []):
        key = str(hold.get("key") or "")
        if hold.get("reason") == "AUTHORITY_DOCUMENT_REVISION_DRIFT" and key in live_keys:
            accepted_live_revision_drifts.append(dict(hold))
            continue
        remaining_holds.append(dict(hold))

    for row in proof.get("authority_documents") or []:
        key = str(row.get("key") or "")
        policy = policy_by_key.get(key, "EXACT_BOUND")
        row["revision_policy"] = policy
        row["revision_match_required"] = policy == "EXACT_BOUND"
        if policy == "READ_CURRENT_LIVE":
            row["observed_revision_accepted_as_live_current"] = row.get("full_read") is True

    full_read_complete = (
        all(row.get("full_read") is True for row in proof.get("authority_documents") or [])
        and all(row.get("full_read") is True for row in proof.get("repo_state_files") or [])
        and not remaining_holds
    )
    proof["holds"] = remaining_holds
    proof["accepted_live_revision_drifts"] = accepted_live_revision_drifts
    proof["full_authority_read_complete"] = full_read_complete
    proof["status"] = "PASS" if full_read_complete else "HOLD"
    proof["next_gate"] = (
        "SOURCE_UNIVERSE_DISCOVERY"
        if full_read_complete
        else "HOLD_AUTHORITY_RECONCILIATION_REQUIRED"
    )
    proof["revision_policy_semantics"] = {
        "EXACT_BOUND": "REVISION_DRIFT_IS_HOLD",
        "READ_CURRENT_LIVE": "FULL_READ_AND_IDENTITY_REQUIRED_REVISION_DRIFT_RECORDED_NOT_HOLD",
    }
    return proof


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
            output_path=None,
            repo_root=repo_root,
            drive_api=drive_api,
        )
    finally:
        _base._resolve_document_binding = original

    proof = apply_drive_revision_policy(manifest, proof)
    proof["revision_namespace"] = "GOOGLE_DRIVE_CURRENT_REVISION_ID"
    proof["legacy_docs_revision_tokens_used_for_drive_comparison"] = False
    if output_path is not None:
        output_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return proof
