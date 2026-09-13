from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from ..config import CANONICAL_CURRENT_FOLDER_NAME, FROZEN_CURRENT_FOLDER_DRIVE_ID
from ..google_drive import build_drive_api
from ..source_parity import FOLDER_MIME, _assert_folder, _download_bytes, _list_children
from .auto_continue import (
    AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE,
    PASS_RESULT_STATUS,
    build_trading_date_scopes,
    find_verified_pass_checkpoint,
    run_governed_auto_continuation,
)
from .contracts import DiscoveryPlan, LANE_ID, PatternDiscoveryContractError, fingerprint
from .drive_store import Lane2DriveStore
from .resilience import call_with_retry
from .runner import _load_plan, _safe_token, run_source_discovery
from .source_reader import GovernedSourceReader

INTAKE_SCHEMA = "A1_LANE2_GOVERNED_AUTOMATIC_INTAKE_V1"
INTAKE_STATE_NAME = "A1_LANE2_AUTOMATIC_INTAKE_STATE.json"

# Kept only so an already-persisted L2I state can be migrated in place without deleting audit history.
INTAKE_STATUS_BASELINE = "BASELINE_INITIALIZED_NO_RETROACTIVE_BACKLOG"
BASELINE_SOURCE = "BASELINE_PRESENT_NOT_AUTO_QUEUED"
LEGACY_BASELINE_POLICY = "CURRENT_READY_UNIVERSE_AT_FIRST_ACTIVATION_IS_BASELINE_NOT_RETROACTIVELY_AUTO_QUEUED"

INTAKE_STATUS_IDLE = "IDLE_ALL_CURRENT_GOVERNED_READY_SOURCES_COMPLETE"
INTAKE_STATUS_WORK_PENDING = "WORK_PENDING_EXISTING_OR_NEW_GOVERNED_SOURCE"
INTAKE_STATUS_RUNNING = "RUNNING_GOVERNED_SOURCE_BACKLOG"
INTAKE_STATUS_COMPLETE = "CURRENT_GOVERNED_READY_UNIVERSE_CORPUS_COMPLETE"
INTAKE_STATUS_HOLD = "HOLD"

FULL_BACKLOG_POLICY = "ALL_CURRENT_AND_FUTURE_GOVERNED_READY_SOURCES_MUST_REACH_CORPUS_COMPLETE"
SOURCE_ORDER_POLICY = "FIRST_GOVERNED_TRADING_DATE_THEN_LAST_GOVERNED_TRADING_DATE_NOT_FILENAME"

PREEXISTING_COMPLETE = "CORPUS_COMPLETE_PREEXISTING"
SOURCE_COMPLETE = "CORPUS_COMPLETE"
SOURCE_QUEUED_EXISTING = "QUEUED_EXISTING_GOVERNED_SOURCE"
SOURCE_QUEUED_NEW = "QUEUED_NEW_GOVERNED_SOURCE"
SOURCE_QUEUED_CHANGED = "QUEUED_CHANGED_GOVERNED_IDENTITY"
SOURCE_QUEUED_RESUME = "QUEUED_RESUME_INCOMPLETE"
SOURCE_RUNNING = "RUNNING"
SOURCE_HOLD = "HOLD"
SOURCE_REMOVED = "REMOVED_FROM_GOVERNED_READY_UNIVERSE"
SOURCE_REPLACEMENT_SAME_CONTENT = "REPLACEMENT_SAME_CONTENT_NO_REPROCESS"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _download_json_dict(api, item: Mapping[str, Any], *, role: str) -> dict[str, Any]:
    file_id = str(item["id"])
    data = call_with_retry(
        lambda: _download_bytes(api, file_id),
        operation=f"lane2.intake.download:{role}:{file_id}",
    )
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PatternDiscoveryContractError(f"AUTOMATIC_INTAKE_{role}_JSON_INVALID:{file_id}") from exc
    if not isinstance(obj, dict):
        raise PatternDiscoveryContractError(f"AUTOMATIC_INTAKE_{role}_NOT_OBJECT:{file_id}")
    return obj


def _trigger_identity(item: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    required = ("source_name", "source_drive_id", "source_sha256", "generation_id")
    missing = [key for key in required if not manifest.get(key)]
    if missing:
        raise PatternDiscoveryContractError(
            f"AUTOMATIC_INTAKE_SOURCE_MANIFEST_IDENTITY_MISSING:{item.get('name')}:{','.join(missing)}"
        )
    return {
        "source_name": str(manifest["source_name"]),
        "source_drive_id": str(manifest["source_drive_id"]),
        "source_sha256": str(manifest["source_sha256"]),
        "generation_id": str(manifest["generation_id"]),
        "data_plane_manifest_file_id": str(item["id"]),
        "data_plane_manifest_modified_time": str(item.get("modifiedTime") or ""),
    }


def _same_trigger_identity(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> bool:
    return bool(left is not None and right is not None and dict(left) == dict(right))


def _same_content_generation(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return (
        str(left.get("source_sha256") or "") == str(right.get("source_sha256") or "")
        and str(left.get("generation_id") or "") == str(right.get("generation_id") or "")
    )


def discover_governed_ready_sources(reader_api) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Dynamically discover every governed source exposed by canonical CURRENT."""
    call_with_retry(
        lambda: _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME),
        operation="lane2.intake.assert_current_folder",
    )
    root = call_with_retry(
        lambda: _list_children(
            reader_api,
            FROZEN_CURRENT_FOLDER_DRIVE_ID,
            fields="id,name,mimeType,size,md5Checksum,modifiedTime",
        ),
        operation="lane2.intake.list_current_root",
    )
    manifest_folders = [
        item for item in root if item.get("mimeType") == FOLDER_MIME and item.get("name") == "00_MANIFESTS"
    ]
    if len(manifest_folders) != 1:
        raise PatternDiscoveryContractError(
            f"AUTOMATIC_INTAKE_MANIFEST_FOLDER_CARDINALITY:{len(manifest_folders)}"
        )
    manifest_folder_id = str(manifest_folders[0]["id"])
    items = call_with_retry(
        lambda: _list_children(
            reader_api,
            manifest_folder_id,
            fields="id,name,mimeType,size,md5Checksum,modifiedTime",
        ),
        operation="lane2.intake.list_source_manifests",
    )
    source_manifest_items = [
        item
        for item in items
        if item.get("mimeType") != FOLDER_MIME
        and str(item.get("name") or "").endswith("__DATA_PLANE_MANIFEST.json")
    ]

    ready: list[dict[str, Any]] = []
    not_ready: list[dict[str, Any]] = []
    for item in source_manifest_items:
        obj = _download_json_dict(reader_api, item, role="SOURCE_MANIFEST")
        identity = _trigger_identity(item, obj)
        invariant_problem = None
        if obj.get("status") == "ACCESS_READY_FOR_AI":
            if obj.get("physical_access_ready") is not True:
                invariant_problem = "SOURCE_PHYSICAL_ACCESS_NOT_READY"
            elif obj.get("sampling_used") is not False or obj.get("filtering_used") is not False:
                invariant_problem = "SOURCE_DATA_PLANE_SAMPLING_OR_FILTERING_DETECTED"
            elif obj.get("behavior_labels_created") is not False:
                invariant_problem = "SOURCE_DATA_PLANE_BEHAVIOR_LABELS_DETECTED"
            elif obj.get("all_fields_preserved") is not True:
                invariant_problem = "SOURCE_DATA_PLANE_NOT_ALL_FIELDS_PRESERVED"
        if invariant_problem:
            raise PatternDiscoveryContractError(
                f"AUTOMATIC_INTAKE_GOVERNED_READY_INVARIANT_FAILED:{identity['source_name']}:{invariant_problem}"
            )
        if obj.get("status") != "ACCESS_READY_FOR_AI":
            not_ready.append(
                {
                    "source_name": identity["source_name"],
                    "source_drive_id": identity["source_drive_id"],
                    "source_sha256": identity["source_sha256"],
                    "status": obj.get("status"),
                }
            )
            continue
        ready.append(identity)

    names = [row["source_name"] for row in ready]
    if len(names) != len(set(names)):
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_DUPLICATE_SOURCE_NAME")
    by_hash: dict[str, list[str]] = {}
    for row in ready:
        by_hash.setdefault(row["source_sha256"], []).append(row["source_name"])
    duplicate_content = {sha: sorted(group) for sha, group in by_hash.items() if len(group) > 1}
    if duplicate_content:
        first_sha = sorted(duplicate_content)[0]
        raise PatternDiscoveryContractError(
            "AUTOMATIC_INTAKE_DUPLICATE_CONTENT:"
            f"SHA256={first_sha}:SOURCES={','.join(duplicate_content[first_sha])}"
        )
    ready.sort(key=lambda row: (row["source_name"], row["source_drive_id"]))
    not_ready.sort(key=lambda row: (row["source_name"], row["source_drive_id"]))
    return ready, not_ready


def _preexisting_complete_states(store: Lane2DriveStore, plan: DiscoveryPlan) -> dict[str, dict[str, Any]]:
    suffix = f"__{_safe_token(plan.plan_id)}__GOVERNED_AUTO_CONTINUATION_STATE.json"
    out: dict[str, dict[str, Any]] = {}
    for item in store._folder_items(store.control_folder_id):
        name = str(item.get("name") or "")
        if not name.endswith(suffix):
            continue
        try:
            obj = json.loads(store.read_bytes(item).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("status") != AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE:
            continue
        if obj.get("plan_fingerprint") != plan.sha256:
            continue
        identity = obj.get("source_identity") or {}
        source_name = str(identity.get("source_name") or "")
        if source_name:
            out[source_name] = obj
    return out


def _completion_matches_trigger(completion: Mapping[str, Any], trigger: Mapping[str, Any]) -> bool:
    identity = completion.get("source_identity") or {}
    return (
        str(identity.get("source_name") or "") == trigger["source_name"]
        and str(identity.get("source_drive_id") or "") == trigger["source_drive_id"]
        and str(identity.get("source_sha256") or "") == trigger["source_sha256"]
        and str(identity.get("generation_id") or "") == trigger["generation_id"]
    )


def initialize_baseline_state(
    *,
    ready_sources: list[dict[str, Any]],
    not_ready_sources: list[dict[str, Any]],
    plan: DiscoveryPlan,
    packets_per_shard: int,
    software_revision: str,
    completion_states: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Initialize the durable universe state.

    The historical function name is retained for compatibility, but the old L2I
    no-retroactive-baseline behavior is superseded. Every governed-ready source that
    is not already verified CORPUS_COMPLETE is queued as existing backlog.
    """
    now = _utc_now()
    sources: dict[str, Any] = {}
    pending: list[str] = []
    for identity in ready_sources:
        source_name = identity["source_name"]
        preexisting = completion_states.get(source_name)
        complete = bool(preexisting and _completion_matches_trigger(preexisting, identity))
        if not complete:
            pending.append(source_name)
        sources[source_name] = {
            "baseline_identity": dict(identity),
            "current_identity": dict(identity),
            "status": PREEXISTING_COMPLETE if complete else SOURCE_QUEUED_EXISTING,
            "auto_eligible": not complete,
            "first_seen_utc": now,
            "last_seen_utc": now,
            "completed_source_identity": dict(preexisting.get("source_identity") or {}) if complete else None,
            "last_result": {
                "status": AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE,
                "last_completed_date": preexisting.get("last_completed_date"),
            }
            if complete
            else None,
            "hold": None,
        }
    return {
        "schema": INTAKE_SCHEMA,
        "lane_id": LANE_ID,
        "status": INTAKE_STATUS_WORK_PENDING if pending else INTAKE_STATUS_COMPLETE,
        "created_at_utc": now,
        "updated_at_utc": now,
        "software_revision": software_revision,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "packets_per_shard": packets_per_shard,
        "baseline_policy": FULL_BACKLOG_POLICY,
        "supersedes_baseline_policy": LEGACY_BASELINE_POLICY,
        "source_order_policy": SOURCE_ORDER_POLICY,
        "baseline_source_universe_fingerprint": fingerprint(ready_sources),
        "sources": sources,
        "not_ready_sources": not_ready_sources,
        "pending_sources": sorted(pending),
        "active_source": None,
        "hold": None,
    }


def classify_current_universe(
    *, state: dict[str, Any], ready_sources: list[dict[str, Any]], not_ready_sources: list[dict[str, Any]]
) -> list[str]:
    """Classify all current sources without silently exempting pre-activation backlog."""
    now = _utc_now()
    records = state.setdefault("sources", {})
    if not isinstance(records, dict):
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_STATE_SOURCES_NOT_OBJECT")
    current = {row["source_name"]: row for row in ready_sources}

    # Explicitly migrate the superseded L2I state in place; do not delete/recreate history.
    if state.get("baseline_policy") == LEGACY_BASELINE_POLICY:
        state["supersedes_baseline_policy"] = LEGACY_BASELINE_POLICY
    state["baseline_policy"] = FULL_BACKLOG_POLICY
    state["source_order_policy"] = SOURCE_ORDER_POLICY

    for source_name, record in records.items():
        if source_name not in current and isinstance(record, dict):
            if record.get("status") not in {SOURCE_REMOVED, SOURCE_HOLD}:
                record["status"] = SOURCE_REMOVED
                record["auto_eligible"] = False
                record["removed_at_utc"] = now
            record["last_seen_utc"] = record.get("last_seen_utc") or now

    pending: list[str] = []
    historical_by_content: dict[tuple[str, str], list[str]] = {}
    for source_name, record in records.items():
        if not isinstance(record, dict):
            continue
        for key in ("current_identity", "baseline_identity"):
            ident = record.get(key)
            if isinstance(ident, dict) and ident.get("source_sha256") and ident.get("generation_id"):
                historical_by_content.setdefault(
                    (str(ident["source_sha256"]), str(ident["generation_id"])), []
                ).append(source_name)

    for source_name, identity in current.items():
        record = records.get(source_name)
        if not isinstance(record, dict):
            same_content_prior = sorted(
                set(historical_by_content.get((identity["source_sha256"], identity["generation_id"]), []))
            )
            if same_content_prior:
                records[source_name] = {
                    "baseline_identity": None,
                    "current_identity": dict(identity),
                    "status": SOURCE_REPLACEMENT_SAME_CONTENT,
                    "auto_eligible": False,
                    "first_seen_utc": now,
                    "last_seen_utc": now,
                    "replacement_of": same_content_prior,
                    "hold": None,
                }
                continue
            records[source_name] = {
                "baseline_identity": None,
                "current_identity": dict(identity),
                "status": SOURCE_QUEUED_NEW,
                "auto_eligible": True,
                "first_seen_utc": now,
                "last_seen_utc": now,
                "hold": None,
            }
            pending.append(source_name)
            continue

        prior_identity = record.get("current_identity")
        prior_status = str(record.get("status") or "")
        record["last_seen_utc"] = now
        if _same_trigger_identity(prior_identity, identity):
            if prior_status == BASELINE_SOURCE:
                record["status"] = SOURCE_QUEUED_EXISTING
                record["auto_eligible"] = True
                record["policy_migrated_at_utc"] = now
                pending.append(source_name)
            elif prior_status in {
                SOURCE_QUEUED_EXISTING,
                SOURCE_QUEUED_NEW,
                SOURCE_QUEUED_CHANGED,
                SOURCE_QUEUED_RESUME,
                SOURCE_RUNNING,
            }:
                record["status"] = SOURCE_QUEUED_RESUME
                record["auto_eligible"] = True
                pending.append(source_name)
            elif prior_status == SOURCE_REMOVED:
                record["status"] = SOURCE_QUEUED_RESUME
                record["auto_eligible"] = True
                record["reappeared_at_utc"] = now
                pending.append(source_name)
            elif prior_status in {SOURCE_COMPLETE, PREEXISTING_COMPLETE, SOURCE_REPLACEMENT_SAME_CONTENT, SOURCE_HOLD}:
                record["auto_eligible"] = False
            else:
                # Unknown unfinished legacy state must not silently disappear from research scope.
                completed = record.get("completed_source_identity")
                if completed:
                    record["auto_eligible"] = False
                else:
                    record["status"] = SOURCE_QUEUED_EXISTING
                    record["auto_eligible"] = True
                    pending.append(source_name)
            continue

        if isinstance(prior_identity, dict) and _same_content_generation(prior_identity, identity):
            record["previous_identity"] = dict(prior_identity)
            record["current_identity"] = dict(identity)
            record["status"] = SOURCE_REPLACEMENT_SAME_CONTENT
            record["auto_eligible"] = False
            record["replacement_same_content_at_utc"] = now
            continue

        record["previous_identity"] = dict(prior_identity) if isinstance(prior_identity, dict) else None
        record["current_identity"] = dict(identity)
        record["status"] = SOURCE_QUEUED_CHANGED
        record["auto_eligible"] = True
        record["identity_changed_at_utc"] = now
        record["hold"] = None
        pending.append(source_name)

    state["not_ready_sources"] = not_ready_sources
    state["pending_sources"] = sorted(set(pending))
    state["updated_at_utc"] = now
    state["status"] = INTAKE_STATUS_WORK_PENDING if pending else INTAKE_STATUS_COMPLETE
    state["hold"] = None
    return state["pending_sources"]


def _validate_state_contract(state: Mapping[str, Any], plan: DiscoveryPlan, packets_per_shard: int) -> None:
    if state.get("schema") != INTAKE_SCHEMA or state.get("lane_id") != LANE_ID:
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_STATE_SCHEMA_OR_LANE_MISMATCH")
    if state.get("plan_id") != plan.plan_id or state.get("plan_fingerprint") != plan.sha256:
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_STATE_PLAN_FINGERPRINT_MISMATCH")
    if int(state.get("packets_per_shard") or -1) != packets_per_shard:
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_STATE_SHARD_POLICY_MISMATCH")


def _validate_reader_identity(reader: GovernedSourceReader, trigger_identity: Mapping[str, Any]) -> dict[str, Any]:
    identity = reader.identity.as_dict()
    source_name = str(identity.get("source_name") or "")
    for key in ("source_name", "source_drive_id", "source_sha256", "generation_id", "data_plane_manifest_file_id"):
        if str(identity.get(key) or "") != str(trigger_identity.get(key) or ""):
            raise PatternDiscoveryContractError(
                f"AUTOMATIC_INTAKE_SOURCE_IDENTITY_CHANGED_DURING_ADMISSION:{source_name}:{key}"
            )
    return identity


def order_source_queue(
    pending_sources: list[str], coverage_by_source: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """Order source envelopes by governed semantic-manifest chronology, never filename chronology."""
    missing = [name for name in pending_sources if name not in coverage_by_source]
    if missing:
        raise PatternDiscoveryContractError(
            f"AUTOMATIC_INTAKE_SOURCE_COVERAGE_MISSING:{','.join(sorted(missing))}"
        )
    return sorted(
        set(pending_sources),
        key=lambda name: (
            str(coverage_by_source[name]["first_trading_date"]),
            str(coverage_by_source[name]["last_trading_date"]),
            str(name),
            str(coverage_by_source[name].get("source_drive_id") or ""),
        ),
    )


def _ordered_pending_sources(
    *,
    pending_sources: list[str],
    current: Mapping[str, Mapping[str, Any]],
    state: dict[str, Any],
) -> list[str]:
    coverage_by_source: dict[str, dict[str, Any]] = {}
    for source_name in pending_sources:
        trigger = current[source_name]
        reader = GovernedSourceReader(build_drive_api(read_write=False), source_name=source_name)
        identity = _validate_reader_identity(reader, trigger)
        scopes = build_trading_date_scopes(reader.semantic_manifest_rows)
        coverage = {
            "source_drive_id": identity["source_drive_id"],
            "first_trading_date": scopes[0].trading_date,
            "last_trading_date": scopes[-1].trading_date,
            "trading_date_count": len(scopes),
            "ticker_day_count": identity["ticker_day_count"],
            "source_data_rows": identity["source_data_rows"],
        }
        coverage_by_source[source_name] = coverage
        state["sources"][source_name]["governed_coverage"] = coverage
    ordered = order_source_queue(pending_sources, coverage_by_source)
    state["pending_sources"] = ordered
    state["source_order_policy"] = SOURCE_ORDER_POLICY
    return ordered


def _run_one_source(
    *,
    source_name: str,
    trigger_identity: Mapping[str, Any],
    plan_path: Path,
    plan: DiscoveryPlan,
    packets_per_shard: int,
    software_revision: str,
    store: Lane2DriveStore,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reader = GovernedSourceReader(build_drive_api(read_write=False), source_name=source_name)
    identity = _validate_reader_identity(reader, trigger_identity)
    scopes = build_trading_date_scopes(reader.semantic_manifest_rows)
    first_scope = scopes[0]
    first_proof = find_verified_pass_checkpoint(
        store=store,
        reader=reader,
        plan=plan,
        scope=first_scope,
    )
    reused_first_pass = first_proof is not None
    if first_proof is None:
        report = run_source_discovery(
            source_name=source_name,
            plan_path=plan_path,
            packets_per_shard=packets_per_shard,
            software_revision=software_revision,
            trading_date=first_scope.trading_date,
            ticker=None,
        )
        if report.get("pass") is not True or report.get("status") not in {
            PASS_RESULT_STATUS,
            "NOOP_ALREADY_COMPLETE",
        }:
            raise PatternDiscoveryContractError(
                f"AUTOMATIC_INTAKE_FIRST_DATE_NOT_PASS:{source_name}:{first_scope.trading_date}:{report.get('status')}"
            )
        first_proof = find_verified_pass_checkpoint(
            store=store,
            reader=reader,
            plan=plan,
            scope=first_scope,
        )
        if first_proof is None:
            raise PatternDiscoveryContractError(
                f"AUTOMATIC_INTAKE_FIRST_DATE_PASS_READBACK_FAILED:{source_name}:{first_scope.trading_date}"
            )

    result = run_governed_auto_continuation(
        source_name=source_name,
        expected_source_drive_id=identity["source_drive_id"],
        expected_source_sha256=identity["source_sha256"],
        plan_path=plan_path,
        expected_plan_fingerprint=plan.sha256,
        packets_per_shard=packets_per_shard,
        software_revision=software_revision,
        anchor_passed_date=first_scope.trading_date,
    )
    if result.get("pass") is not True or result.get("status") != AUTO_CONTINUATION_STATUS_CORPUS_COMPLETE:
        raise PatternDiscoveryContractError(
            f"AUTOMATIC_INTAKE_CORPUS_NOT_COMPLETE:{source_name}:{result.get('status')}"
        )
    return identity, {
        **result,
        "first_trading_date": first_scope.trading_date,
        "last_trading_date": scopes[-1].trading_date,
        "first_date_reused_existing_verified_pass": reused_first_pass,
    }


def run_automatic_lane2_intake(
    *,
    plan_path: Path,
    expected_plan_fingerprint: str,
    packets_per_shard: int,
    software_revision: str,
    bootstrap_existing_as_baseline: bool = False,
) -> dict[str, Any]:
    # bootstrap_existing_as_baseline is intentionally ignored. It is retained only so an
    # older workflow invocation cannot resurrect the superseded no-retroactive policy.
    _ = bootstrap_existing_as_baseline
    if packets_per_shard <= 0:
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_PACKETS_PER_SHARD_MUST_BE_POSITIVE")
    if not software_revision or software_revision == "LOCAL_UNVERSIONED":
        raise PatternDiscoveryContractError("AUTOMATIC_INTAKE_SOFTWARE_REVISION_REQUIRED")
    plan = _load_plan(plan_path)
    if plan.sha256 != expected_plan_fingerprint:
        raise PatternDiscoveryContractError(
            f"AUTOMATIC_INTAKE_PLAN_FINGERPRINT_MISMATCH:{plan.sha256}"
        )

    reader_api = build_drive_api(read_write=False)
    ready_sources, not_ready_sources = discover_governed_ready_sources(reader_api)
    store = Lane2DriveStore(build_drive_api(read_write=True))
    state = store.read_json_optional(store.control_folder_id, INTAKE_STATE_NAME)

    if state is None:
        state = initialize_baseline_state(
            ready_sources=ready_sources,
            not_ready_sources=not_ready_sources,
            plan=plan,
            packets_per_shard=packets_per_shard,
            software_revision=software_revision,
            completion_states=_preexisting_complete_states(store, plan),
        )
        store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)
    else:
        _validate_state_contract(state, plan, packets_per_shard)

    pending = classify_current_universe(
        state=state,
        ready_sources=ready_sources,
        not_ready_sources=not_ready_sources,
    )
    state["software_revision"] = software_revision
    current = {row["source_name"]: row for row in ready_sources}
    if pending:
        pending = _ordered_pending_sources(
            pending_sources=pending,
            current=current,
            state=state,
        )
    store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)

    if not pending:
        return {
            "schema": INTAKE_SCHEMA,
            "lane_id": LANE_ID,
            "pass": True,
            "status": INTAKE_STATUS_IDLE,
            "run_required": False,
            "ready_source_count": len(ready_sources),
            "not_ready_source_count": len(not_ready_sources),
            "pending_sources": [],
            "policy": FULL_BACKLOG_POLICY,
        }

    active_source: str | None = None
    processed: list[str] = []
    try:
        state["status"] = INTAKE_STATUS_RUNNING
        state["updated_at_utc"] = _utc_now()
        store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)
        for source_name in pending:
            active_source = source_name
            record = state["sources"][source_name]
            record["status"] = SOURCE_RUNNING
            record["auto_eligible"] = True
            record["started_at_utc"] = record.get("started_at_utc") or _utc_now()
            record["last_resume_at_utc"] = _utc_now()
            record["hold"] = None
            state["active_source"] = source_name
            state["updated_at_utc"] = _utc_now()
            store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)

            full_identity, result = _run_one_source(
                source_name=source_name,
                trigger_identity=current[source_name],
                plan_path=plan_path,
                plan=plan,
                packets_per_shard=packets_per_shard,
                software_revision=software_revision,
                store=store,
            )
            record["status"] = SOURCE_COMPLETE
            record["auto_eligible"] = False
            record["completed_source_identity"] = full_identity
            record["last_result"] = result
            record["completed_at_utc"] = _utc_now()
            record["hold"] = None
            processed.append(source_name)
            state["pending_sources"] = [name for name in state.get("pending_sources", []) if name != source_name]
            state["active_source"] = None
            state["updated_at_utc"] = _utc_now()
            store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)
    except Exception as exc:
        state["status"] = INTAKE_STATUS_HOLD
        state["updated_at_utc"] = _utc_now()
        state["active_source"] = active_source
        state["hold"] = {
            "source_name": active_source,
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "resume_rule": "RESUME_AUTOMATIC_INTAKE_FROM_PERSISTED_SOURCE_AND_DATE_CHECKPOINTS_DO_NOT_RESTART_ACCEPTED_WORK",
        }
        if active_source and active_source in state.get("sources", {}):
            state["sources"][active_source]["status"] = SOURCE_HOLD
            state["sources"][active_source]["hold"] = dict(state["hold"])
        store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)
        raise

    state["status"] = INTAKE_STATUS_COMPLETE
    state["active_source"] = None
    state["pending_sources"] = []
    state["hold"] = None
    state["updated_at_utc"] = _utc_now()
    upload = store.upsert_json(folder_id=store.control_folder_id, name=INTAKE_STATE_NAME, obj=state)
    return {
        "schema": INTAKE_SCHEMA,
        "lane_id": LANE_ID,
        "pass": True,
        "status": INTAKE_STATUS_COMPLETE,
        "run_required": True,
        "processed_sources": processed,
        "ready_source_count": len(ready_sources),
        "not_ready_source_count": len(not_ready_sources),
        "state_file": upload,
        "policy": FULL_BACKLOG_POLICY,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lane2-automatic-intake")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--plan-fingerprint", required=True)
    parser.add_argument("--packets-per-shard", required=True, type=int)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument(
        "--bootstrap-existing-as-baseline",
        action="store_true",
        help="Deprecated compatibility flag; existing governed RAW is now mandatory backlog, never exempt baseline.",
    )
    args = parser.parse_args(argv)
    result = run_automatic_lane2_intake(
        plan_path=args.plan,
        expected_plan_fingerprint=args.plan_fingerprint,
        packets_per_shard=args.packets_per_shard,
        software_revision=args.software_revision,
        bootstrap_existing_as_baseline=args.bootstrap_existing_as_baseline,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("pass") else 9


if __name__ == "__main__":
    raise SystemExit(main())
