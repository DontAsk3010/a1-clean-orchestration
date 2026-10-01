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
    """Resolve a bootstrap row in the Drive-revision namespace.

    Kept only as a compatibility helper for callers/tests that need to inspect the
    manifest binding directly. The CURRENT authority bootstrap core already compares
    ``drive_revision_id`` natively and therefore does not require resolver monkeypatching.
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
    """Run the CURRENT bootstrap using Drive-native revision IDs.

    The authority bootstrap core now owns full-read validation and compares each
    manifest row's ``drive_revision_id`` directly. This adapter only supplies the
    current files/API, then applies the one explicit READ_CURRENT_LIVE exception.
    It intentionally does not monkeypatch the core resolver and does not depend on
    the removed legacy ``run_authority_bootstrap`` entry point.
    """
    import json

    manifest_raw = manifest_path.read_bytes()
    lock_raw = authority_lock_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    lock = json.loads(lock_raw.decode("utf-8-sig"))
    validate_drive_revision_bindings(manifest)

    api = drive_api if drive_api is not None else _base.build_drive_api()
    proof = _base.build_authority_sync_proof(
        manifest=manifest,
        lock=lock,
        repo_root=repo_root.resolve(),
        drive_api=api,
        manifest_sha256=_base._sha256_bytes(manifest_raw),
        lock_sha256=_base._sha256_bytes(lock_raw),
    )

    proof = apply_drive_revision_policy(manifest, proof)
    proof["revision_namespace"] = "GOOGLE_DRIVE_CURRENT_REVISION_ID"
    proof["legacy_docs_revision_tokens_used_for_drive_comparison"] = False
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return proof
