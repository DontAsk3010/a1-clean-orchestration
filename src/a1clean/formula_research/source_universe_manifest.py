from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from typing import Any

SCHEMA = "A1_CLEAN_SOURCE_UNIVERSE_MANIFEST_V1"
STATUS_PASS = "PASS"
STATUS_HOLD = "HOLD"

# Historical evidence only. This list proves backward compatibility and ordering;
# it is never a final-universe cardinality invariant.
HISTORICAL_BASELINE_SOURCE_NAMES = (
    "Raw Des 02-31-2024.csv",
    "Raw Jan 01-31-2025.csv",
    "Raw Feb 03-28-2025.csv",
    "Raw Maret 03-31-2025.csv",
    "Raw April 01-30-2025.csv",
    "Raw Mei 01-30-2025.csv",
    "Raw Juni 02-30-2025.csv",
    "Raw Juli 01-31-2025.csv",
    "Raw Agust 01-29-2025.csv",
    "Raw Sep 01-30-2025.csv",
    "Raw Oct 01-31-2025.csv",
    "Raw Nov 03-29-2025.csv",
    "Raw Des 01-31-2025.csv",
    "Raw Jan 01-30-2026.csv",
    "Raw Feb 02-27-2026.csv",
    "Raw Mar 02-31-2026.csv",
    "Raw Apr 01-30-2026.csv",
    "Raw Mei 01-29-2026.csv",
)


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(obj: Any) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _hold(reason: str, **evidence: Any) -> dict[str, Any]:
    return {"reason": reason, **evidence}


def _discovery_rows(discovery: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not discovery:
        return []
    return [dict(row) for row in discovery.get("files", [])]


def _active_rows(global_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in global_manifest.get("sources", [])]


def _active_readiness(row: dict[str, Any]) -> tuple[str, bool]:
    required = (
        row.get("source_drive_id"),
        row.get("source_name"),
        row.get("source_sha256"),
        row.get("first_observed_date"),
        row.get("last_observed_date"),
    )
    if not all(required):
        return "NOT_READY_REQUIRED_METADATA_MISSING", False
    status = str(row.get("status") or "").upper()
    if status.startswith("HOLD") or status.startswith("FAIL"):
        return "NOT_READY_DATA_PLANE_STATUS", False
    return "DATA_PLANE_READY_SEMANTIC_READINESS_EXTERNAL", True


def build_source_universe_manifest(
    *,
    global_manifest: dict[str, Any],
    discovery: dict[str, Any] | None = None,
    authority_revision: str,
    discovery_time_utc: str,
    required_source_names: Sequence[str] = (),
    authority_sync: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the governed dynamic source universe from accepted data-plane state.

    Membership authority is GLOBAL_DATA_PLANE_MANIFEST.sources. Discovery may
    surface additional physical candidates, but a candidate is never silently
    promoted merely because it exists in the RAW folder. Unknown candidates are
    explicit HOLD evidence until the governed data plane accepts/classifies them.
    """

    active = _active_rows(global_manifest)
    discovered = _discovery_rows(discovery)
    holds: list[dict[str, Any]] = []

    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_digest: dict[str, list[dict[str, Any]]] = {}
    for row in active:
        source_id = str(row.get("source_drive_id") or "")
        source_name = str(row.get("source_name") or "")
        digest = str(row.get("source_sha256") or "")
        if not source_id:
            holds.append(_hold("ACTIVE_SOURCE_ID_MISSING", source_name=source_name))
        elif source_id in by_id:
            holds.append(_hold("DUPLICATE_ACTIVE_SOURCE_ID", source_drive_id=source_id))
        else:
            by_id[source_id] = row
        by_name.setdefault(source_name, []).append(row)
        if digest:
            by_digest.setdefault(digest, []).append(row)

    for name, rows in sorted(by_name.items()):
        if not name:
            holds.append(_hold("ACTIVE_SOURCE_NAME_MISSING"))
        elif len(rows) > 1:
            holds.append(_hold("DUPLICATE_ACTIVE_SOURCE_NAME", source_name=name))
    for digest, rows in sorted(by_digest.items()):
        if len(rows) > 1:
            holds.append(
                _hold(
                    "DUPLICATE_ACTIVE_SOURCE_CONTENT",
                    source_sha256=digest,
                    source_names=sorted(str(r.get("source_name") or "") for r in rows),
                )
            )

    discovered_by_id: dict[str, dict[str, Any]] = {}
    discovered_name_counts: dict[str, int] = {}
    for row in discovered:
        source_id = str(row.get("drive_file_id") or row.get("drive_id") or "")
        name = str(row.get("name") or "")
        if source_id:
            if source_id in discovered_by_id:
                holds.append(_hold("DUPLICATE_DISCOVERY_SOURCE_ID", source_drive_id=source_id))
            discovered_by_id[source_id] = row
        discovered_name_counts[name] = discovered_name_counts.get(name, 0) + 1
    for name, count in sorted(discovered_name_counts.items()):
        if count > 1:
            holds.append(_hold("DUPLICATE_DISCOVERY_SOURCE_NAME", source_name=name, count=count))

    if discovered:
        for source_id, row in sorted(by_id.items()):
            if source_id not in discovered_by_id:
                holds.append(
                    _hold(
                        "ACTIVE_CANONICAL_SOURCE_MISSING_FROM_DISCOVERY",
                        source_drive_id=source_id,
                        source_name=row.get("source_name"),
                    )
                )
        for source_id, row in sorted(discovered_by_id.items()):
            if source_id not in by_id:
                holds.append(
                    _hold(
                        "UNRECOGNIZED_DISCOVERY_CANDIDATE",
                        source_drive_id=source_id,
                        source_name=row.get("name"),
                        identity_state=row.get("identity_state"),
                    )
                )

    required = tuple(str(name) for name in required_source_names)
    active_names = set(by_name)
    for name in required:
        if name not in active_names:
            holds.append(_hold("REQUIRED_CANONICAL_SOURCE_MISSING", source_name=name))

    ordered_active = sorted(
        active,
        key=lambda row: (
            str(row.get("first_observed_date") or "9999-99-99"),
            str(row.get("first_observed_time") or "99:99:99"),
            str(row.get("source_name") or ""),
            str(row.get("source_drive_id") or ""),
        ),
    )

    previous: dict[str, Any] | None = None
    for row in ordered_active:
        first_date = str(row.get("first_observed_date") or "")
        last_date = str(row.get("last_observed_date") or "")
        if not first_date or not last_date or first_date > last_date:
            holds.append(
                _hold(
                    "SOURCE_OBSERVATION_ENVELOPE_INVALID",
                    source_name=row.get("source_name"),
                    first_date=first_date or None,
                    last_date=last_date or None,
                )
            )
        if previous is not None:
            prev_last = str(previous.get("last_observed_date") or "")
            if prev_last and first_date and prev_last >= first_date:
                holds.append(
                    _hold(
                        "SOURCE_DATE_OVERLAP_OR_CONFLICT",
                        previous_source=previous.get("source_name"),
                        previous_last_date=prev_last,
                        source_name=row.get("source_name"),
                        first_date=first_date,
                    )
                )
        previous = row

    records: list[dict[str, Any]] = []
    for ordering_index, row in enumerate(ordered_active):
        readiness, ready = _active_readiness(row)
        if not ready:
            holds.append(
                _hold(
                    "ACTIVE_SOURCE_NOT_READY",
                    source_drive_id=row.get("source_drive_id"),
                    source_name=row.get("source_name"),
                    readiness=readiness,
                )
            )
        records.append(
            {
                "canonical_source_identity": str(row.get("source_drive_id") or ""),
                "source_drive_id": row.get("source_drive_id"),
                "source_name": row.get("source_name"),
                "digest_sha256": row.get("source_sha256"),
                "eligibility": "ELIGIBLE_GOVERNED_ACTIVE",
                "ready": ready,
                "readiness": readiness,
                "first_date": row.get("first_observed_date"),
                "first_time": row.get("first_observed_time"),
                "last_date": row.get("last_observed_date"),
                "last_time": row.get("last_observed_time"),
                "schema_source_capability": {
                    "generation_id": row.get("generation_id") or global_manifest.get("generation_id"),
                    "data_plane_impl_version": row.get("data_plane_impl_version")
                    or global_manifest.get("data_plane_impl_version"),
                    "source_data_rows": row.get("source_data_rows"),
                    "ticker_day_objects": row.get("ticker_day_objects"),
                    "physical_shard_count": row.get("physical_shard_count"),
                    "semantic_bundle_count": row.get("semantic_bundle_count"),
                    "market_day_index": row.get("market_day_index"),
                },
                "provenance": {
                    "canonical_source_home_drive_id": global_manifest.get("canonical_source_home_drive_id"),
                    "delta_refresh_id": global_manifest.get("delta_refresh_id"),
                    "delta_action": row.get("delta_action"),
                    "source_modified_time": row.get("source_modified_time"),
                },
                "ordering_key": {
                    "index": ordering_index,
                    "first_date": row.get("first_observed_date"),
                    "first_time": row.get("first_observed_time"),
                    "source_name": row.get("source_name"),
                    "source_drive_id": row.get("source_drive_id"),
                },
                "discovery_time_utc": discovery_time_utc,
                "authority_revision": authority_revision,
            }
        )

    authority_sync_summary = None
    if authority_sync is not None:
        authority_sync_summary = {
            "schema": authority_sync.get("schema"),
            "status": authority_sync.get("status"),
            "full_authority_read_complete": authority_sync.get("full_authority_read_complete"),
            "authority_document_count": authority_sync.get("authority_document_count"),
            "repo_state_file_count": authority_sync.get("repo_state_file_count"),
            "authority_corpus_sha256": authority_sync.get("authority_corpus_sha256"),
            "bootstrap_manifest_sha256": authority_sync.get("bootstrap_manifest_sha256"),
            "active_authority_lock_sha256": authority_sync.get("active_authority_lock_sha256"),
            "data_preservation_contract_sha256": authority_sync.get("data_preservation_contract_sha256"),
            "required_data_family_registry_sha256": authority_sync.get("required_data_family_registry_sha256"),
        }
        if authority_sync_summary["status"] != "PASS" or authority_sync_summary["full_authority_read_complete"] is not True:
            holds.append(_hold("AUTHORITY_SYNC_NOT_PASS"))

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS_HOLD if holds else STATUS_PASS,
        "dynamic_source_universe_required": True,
        "fixed_source_count_as_invariant_forbidden": True,
        "historical_baseline_source_count_observed": len(HISTORICAL_BASELINE_SOURCE_NAMES),
        "historical_baseline_count_is_not_universe_invariant": True,
        "authority_revision": authority_revision,
        "authority_sync": authority_sync_summary,
        "discovery_time_utc": discovery_time_utc,
        "source_count": len(records),
        "source_names_in_order": [str(row.get("source_name") or "") for row in records],
        "sources": records,
        "holds": holds,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def source_names_from_manifest(manifest: dict[str, Any], *, require_pass: bool = True) -> tuple[str, ...]:
    if require_pass and manifest.get("status") != STATUS_PASS:
        reasons = [str(row.get("reason")) for row in manifest.get("holds", [])]
        raise RuntimeError("SOURCE_UNIVERSE_MANIFEST_HOLD:" + ",".join(reasons))
    rows = list(manifest.get("sources", []))
    names: list[str] = []
    for row in rows:
        if row.get("eligibility") != "ELIGIBLE_GOVERNED_ACTIVE" or row.get("ready") is not True:
            if require_pass:
                raise RuntimeError(f"SOURCE_UNIVERSE_SOURCE_NOT_READY:{row.get('source_name')}")
            continue
        names.append(str(row.get("source_name") or ""))
    if not names and require_pass:
        raise RuntimeError("SOURCE_UNIVERSE_EMPTY")
    if len(names) != len(set(names)):
        raise RuntimeError("SOURCE_UNIVERSE_DUPLICATE_SOURCE_NAME")
    return tuple(names)


def manifest_digest_is_valid(manifest: dict[str, Any]) -> bool:
    payload = dict(manifest)
    actual = str(payload.pop("manifest_digest", ""))
    return bool(actual) and actual == _digest(payload)


def assert_historical_baseline_order(source_names: Iterable[str]) -> None:
    names = tuple(source_names)
    positions = [names.index(name) for name in HISTORICAL_BASELINE_SOURCE_NAMES if name in names]
    if positions != sorted(positions):
        raise RuntimeError("HISTORICAL_BASELINE_SOURCE_ORDER_DRIFT")
