from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import FROZEN_GENERATION_ID, FROZEN_IMPL_VERSION


def source_from_preflight(row: dict) -> dict:
    return {
        "source_drive_id": str(row.get("drive_id") or ""),
        "source_name": str(row.get("name") or ""),
        "source_size_bytes": row.get("drive_size"),
        "source_modified_time": row.get("drive_modified_time"),
        "source_md5": row.get("drive_md5"),
        "source_sha256": row.get("local_sha256"),
        "identity_status": row.get("status"),
        "local_path": row.get("local_path"),
    }


def public_source_identity(row: dict) -> dict:
    return {
        "source_drive_id": row.get("source_drive_id"),
        "source_name": row.get("source_name"),
        "source_size_bytes": row.get("source_size_bytes"),
        "source_modified_time": row.get("source_modified_time"),
        "source_sha256": row.get("source_sha256"),
    }


def source_row_by_id(preflight: dict) -> dict[str, dict]:
    return {
        str(row.get("drive_id")): row
        for row in preflight.get("required_sources", [])
        if row.get("drive_id")
    }


def _fingerprint(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def source_universe_fingerprint(preflight: dict) -> str:
    rows = []
    for row in preflight.get("required_sources", []):
        rows.append(
            {
                "source_drive_id": row.get("drive_id"),
                "source_name": row.get("name"),
                "source_size_bytes": row.get("drive_size"),
                "source_modified_time": row.get("drive_modified_time"),
                "source_md5": row.get("drive_md5"),
                "source_sha256": row.get("local_sha256"),
                "status": row.get("status"),
            }
        )
    rows.sort(key=lambda row: (str(row.get("source_name")), str(row.get("source_drive_id"))))
    return _fingerprint(rows)


def persistent_state_fingerprint(persistent_state: dict) -> str:
    payload = {
        "state_version": persistent_state.get("state_version"),
        "generation_id": persistent_state.get("generation_id"),
        "data_plane_impl_version": persistent_state.get("data_plane_impl_version"),
        "sources": persistent_state.get("sources") or {},
    }
    return _fingerprint(payload)


def classify_delta_state(*, preflight: dict, persistent_state: dict) -> dict:
    """Classify the canonical source transition from exact governed evidence.

    Source membership comes only from the canonical Drive preflight. SHA256 is
    computed during the same local read pass that proves Drive MD5 identity.
    """

    current = [source_from_preflight(row) for row in preflight.get("required_sources", [])]
    prior = {
        str(key): dict(value)
        for key, value in (persistent_state.get("sources") or {}).items()
    }
    holds: list[dict] = []

    if persistent_state.get("generation_id") != FROZEN_GENERATION_ID:
        holds.append(
            {
                "reason": "PERSISTENT_STATE_GENERATION_MISMATCH",
                "expected": FROZEN_GENERATION_ID,
                "actual": persistent_state.get("generation_id"),
            }
        )
    if persistent_state.get("data_plane_impl_version") != FROZEN_IMPL_VERSION:
        holds.append(
            {
                "reason": "PERSISTENT_STATE_IMPLEMENTATION_MISMATCH",
                "expected": FROZEN_IMPL_VERSION,
                "actual": persistent_state.get("data_plane_impl_version"),
            }
        )

    for row in current:
        if row.get("identity_status") != "PASS_EXACT_MD5":
            holds.append(
                {
                    "reason": "CANONICAL_SOURCE_IDENTITY_NOT_EXACT",
                    **public_source_identity(row),
                    "identity_status": row.get("identity_status"),
                }
            )
        if not row.get("source_sha256"):
            holds.append(
                {
                    "reason": "LOCAL_SHA256_MISSING",
                    **public_source_identity(row),
                }
            )

    current_by_id = {
        row["source_drive_id"]: row
        for row in current
        if row.get("source_drive_id")
    }
    if len(current_by_id) != len(current):
        holds.append({"reason": "CURRENT_SOURCE_ID_DUPLICATE_OR_MISSING"})

    by_hash: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for row in current:
        if row.get("source_sha256"):
            by_hash.setdefault(str(row["source_sha256"]), []).append(row)
        by_name.setdefault(str(row.get("source_name")), []).append(row)
    for digest, rows in sorted(by_hash.items()):
        if len(rows) > 1:
            holds.append(
                {
                    "reason": "DUPLICATE_CURRENT_SOURCE_CONTENT",
                    "source_sha256": digest,
                    "sources": [public_source_identity(row) for row in rows],
                }
            )
    for name, rows in sorted(by_name.items()):
        if len(rows) > 1:
            holds.append(
                {
                    "reason": "DUPLICATE_CURRENT_SOURCE_NAME",
                    "source_name": name,
                    "source_drive_ids": [row.get("source_drive_id") for row in rows],
                }
            )

    verified_unchanged: list[dict] = []
    changed_rebuilt: list[dict] = []
    new_processed: list[dict] = []
    replacement_same_content: list[dict] = []
    consumed_prior_ids: set[str] = set()

    prior_by_name: dict[str, list[tuple[str, dict]]] = {}
    prior_by_hash: dict[str, list[tuple[str, dict]]] = {}
    for prior_id, state in prior.items():
        prior_by_name.setdefault(str(state.get("source_name")), []).append((prior_id, state))
        if state.get("source_sha256"):
            prior_by_hash.setdefault(str(state["source_sha256"]), []).append((prior_id, state))

    unmatched_current: list[dict] = []
    for row in sorted(
        current,
        key=lambda item: (str(item.get("source_name")), str(item.get("source_drive_id"))),
    ):
        source_id = str(row.get("source_drive_id"))
        old = prior.get(source_id)
        if old is None:
            unmatched_current.append(row)
            continue
        consumed_prior_ids.add(source_id)
        unchanged = (
            row.get("source_sha256") == old.get("source_sha256")
            and row.get("source_name") == old.get("source_name")
            and int(row.get("source_size_bytes") or -1)
            == int(old.get("source_size_bytes") or -2)
        )
        if unchanged:
            verified_unchanged.append(public_source_identity(row))
        else:
            changed_rebuilt.append(
                {
                    **public_source_identity(row),
                    "previous_source_drive_id": source_id,
                    "previous_source_name": old.get("source_name"),
                    "previous_source_sha256": old.get("source_sha256"),
                    "change_reason": "EXISTING_DRIVE_ID_CONTENT_OR_IDENTITY_CHANGED",
                }
            )

    still_unmatched: list[dict] = []
    for row in unmatched_current:
        name_candidates = [
            (pid, state)
            for pid, state in prior_by_name.get(str(row.get("source_name")), [])
            if pid not in consumed_prior_ids
        ]
        if len(name_candidates) == 1:
            prior_id, old = name_candidates[0]
            consumed_prior_ids.add(prior_id)
            if row.get("source_sha256") == old.get("source_sha256"):
                replacement_same_content.append(
                    {
                        **public_source_identity(row),
                        "previous_source_drive_id": prior_id,
                        "previous_source_name": old.get("source_name"),
                        "previous_source_sha256": old.get("source_sha256"),
                    }
                )
            else:
                changed_rebuilt.append(
                    {
                        **public_source_identity(row),
                        "previous_source_drive_id": prior_id,
                        "previous_source_name": old.get("source_name"),
                        "previous_source_sha256": old.get("source_sha256"),
                        "change_reason": "SAME_CANONICAL_NAME_REPLACED_WITH_DIFFERENT_CONTENT",
                    }
                )
        elif len(name_candidates) > 1:
            holds.append(
                {
                    "reason": "AMBIGUOUS_PRIOR_NAME_REPLACEMENT",
                    "source_name": row.get("source_name"),
                    "prior_ids": [pid for pid, _ in name_candidates],
                }
            )
        else:
            still_unmatched.append(row)

    for row in still_unmatched:
        hash_candidates = [
            (pid, state)
            for pid, state in prior_by_hash.get(str(row.get("source_sha256")), [])
            if pid not in consumed_prior_ids
        ]
        if len(hash_candidates) == 1:
            prior_id, old = hash_candidates[0]
            consumed_prior_ids.add(prior_id)
            replacement_same_content.append(
                {
                    **public_source_identity(row),
                    "previous_source_drive_id": prior_id,
                    "previous_source_name": old.get("source_name"),
                    "previous_source_sha256": old.get("source_sha256"),
                }
            )
        elif len(hash_candidates) > 1:
            holds.append(
                {
                    "reason": "AMBIGUOUS_PRIOR_CONTENT_REPLACEMENT",
                    "source_sha256": row.get("source_sha256"),
                    "prior_ids": [pid for pid, _ in hash_candidates],
                }
            )
        else:
            new_processed.append(public_source_identity(row))

    removed_purged = [
        {
            "source_drive_id": prior_id,
            "source_name": state.get("source_name"),
            "source_sha256": state.get("source_sha256"),
        }
        for prior_id, state in sorted(
            prior.items(),
            key=lambda item: (str(item[1].get("source_name")), item[0]),
        )
        if prior_id not in consumed_prior_ids
    ]

    return {
        "pass": not holds,
        "verified_unchanged": verified_unchanged,
        "new_processed": new_processed,
        "changed_rebuilt": changed_rebuilt,
        "removed_purged": removed_purged,
        "replacement_same_content": replacement_same_content,
        "holds": holds,
        "active_source_count": len(current),
        "source_count_is_not_an_invariant": True,
    }
