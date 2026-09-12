from __future__ import annotations

import hashlib
import json
from typing import Any

from .config import (
    BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
    BEHAVIOR_CONTROL_FOLDER_NAME,
    FROZEN_GENERATION_ID,
)
from .source_parity import FOLDER_MIME, _assert_folder, _download_json, _list_children

SEMANTIC_LEDGER_SCHEMA = "A1_PERSISTENT_SEMANTIC_RESEARCH_STATE_V1"
SEMANTIC_WORK_QUEUE_SCHEMA = "A1_AI_SEMANTIC_WORK_QUEUE_V1"
SEMANTIC_RUNTIME_SCHEMA = "A1_SEMANTIC_RUNTIME_INPUT_SNAPSHOT_V1"
SEMANTIC_CONTRACT_ID = (
    "MASTER_19A__BEHAVIOR_HANDBOOK_32__AUTOMATION_F2__DUAL_STATE_REALTIME_READY_20260912"
)
SEMANTIC_CONTRACT_FINGERPRINT = hashlib.sha256(
    SEMANTIC_CONTRACT_ID.encode("utf-8")
).hexdigest()


def _fingerprint(payload: Any) -> str:
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _chronological_sources(sources: list[dict]) -> list[dict]:
    return sorted(
        sources,
        key=lambda row: (
            str(row.get("first_observed_date") or "9999-99-99"),
            str(row.get("first_observed_time") or "99:99:99"),
            str(row.get("source_name") or ""),
            str(row.get("source_drive_id") or ""),
        ),
    )


def _status_from_checkpoint(checkpoint: dict) -> str:
    raw = str(checkpoint.get("status") or "").strip().upper()
    date_scope = checkpoint.get("date_scope") or {}
    remaining = date_scope.get("remaining_count")
    if "HOLD" in raw or raw in {"FAILED", "FAIL"}:
        return "HOLD"
    if raw in {
        "COMPLETE",
        "PASS",
        "CLOSED",
        "CLOSED_PASS",
        "DATE_CLOSED",
        "DATE_CLOSED_PASS",
        "SOURCE_COMPLETE",
        "SOURCE_CLOSED_PASS",
        "BEHAVIOR_RESEARCH_PASS",
    }:
        return "COMPLETE"
    if raw in {"NOT_STARTED", "QUEUED"}:
        return raw
    if "DATE_OPEN" in raw:
        return "DATE_OPEN"
    if "IN_PROGRESS" in raw:
        return "IN_PROGRESS"
    if isinstance(remaining, int) and remaining > 0:
        return "DATE_OPEN"
    if remaining == 0:
        return "WAITING_RECONCILIATION"
    if raw:
        return "PARTIAL"
    return "UNKNOWN_NEEDS_RECONCILIATION"


def _checkpoint_projection(checkpoint: dict, *, file_meta: dict) -> dict:
    source = checkpoint.get("source") or {}
    date_scope = checkpoint.get("date_scope") or {}
    accounting = checkpoint.get("event_accounting") or {}
    consistency = checkpoint.get("consistency_test") or {}
    explicit_watermark = (
        checkpoint.get("semantic_processing_watermark")
        or checkpoint.get("last_verified_source_timestamp")
    )
    return {
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "checkpoint_file_id": file_meta.get("id"),
        "checkpoint_file_name": file_meta.get("name"),
        "checkpoint_modified_time": file_meta.get("modifiedTime"),
        "workstream": checkpoint.get("workstream"),
        "source_drive_id": source.get("source_drive_id"),
        "source_name": source.get("source_name"),
        "source_sha256": source.get("source_sha256"),
        "semantic_generation_id": source.get("generation_id"),
        "source_mode": checkpoint.get("source_mode") or source.get("source_mode") or "HISTORICAL_REPLAY",
        "semantic_state": _status_from_checkpoint(checkpoint),
        "checkpoint_status": checkpoint.get("status"),
        "current_trading_date": source.get("trading_date") or date_scope.get("trading_date"),
        "total_ticker_context_paths": date_scope.get("total_ticker_context_paths"),
        "completed_ticker_context_paths": date_scope.get("completed_ticker_context_paths"),
        "remaining_ticker_context_paths": date_scope.get("remaining_count"),
        "completed_tickers": date_scope.get("completed") or [],
        "actual_source_rows_read_in_completed_ticker_days": date_scope.get(
            "actual_source_rows_read_in_completed_ticker_days"
        ),
        "event_journey_count": accounting.get("event_journey_objects"),
        "observation_count": accounting.get("observations"),
        "open_carry_count": accounting.get("open_carry_objects"),
        "next_exact_resume_point": checkpoint.get("next_exact_resume_point"),
        "last_verified_source_record": checkpoint.get("last_verified_source_record"),
        "last_verified_source_timestamp": explicit_watermark,
        "cross_ticker_reconciliation_state": (
            "PENDING"
            if consistency.get("date_reconciliation_pending") is True
            or date_scope.get("date_close_allowed") is False
            else "UNKNOWN"
        ),
        "rubric_version": consistency.get("rubric_version"),
    }


def discover_semantic_runtime(reader_api) -> dict:
    """Read semantic work-state inputs without turning them into a data-plane gate."""
    runtime = {
        "schema": SEMANTIC_RUNTIME_SCHEMA,
        "control_folder_drive_id": BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
        "control_folder_name": BEHAVIOR_CONTROL_FOLDER_NAME,
        "status": "AVAILABLE",
        "prior_ledger": None,
        "checkpoint_snapshots": [],
        "holds": [],
    }
    try:
        _assert_folder(
            reader_api,
            BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
            BEHAVIOR_CONTROL_FOLDER_NAME,
        )
        items = _list_children(
            reader_api,
            BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
            fields="id,name,mimeType,size,md5Checksum,modifiedTime",
        )
    except Exception as exc:
        runtime["status"] = "SEMANTIC_CONTROL_UNAVAILABLE"
        runtime["holds"].append(
            {
                "reason": "SEMANTIC_CONTROL_FOLDER_UNAVAILABLE",
                "type": type(exc).__name__,
                "message": str(exc),
            }
        )
        runtime["fingerprint"] = semantic_runtime_fingerprint(runtime)
        return runtime

    ledgers = [
        item
        for item in items
        if item.get("mimeType") != FOLDER_MIME
        and item.get("name") == "PERSISTENT_SEMANTIC_RESEARCH_STATE.json"
    ]
    if len(ledgers) > 1:
        runtime["status"] = "SEMANTIC_STATE_RECONCILIATION_REQUIRED"
        runtime["holds"].append(
            {
                "reason": "DUPLICATE_PERSISTENT_SEMANTIC_LEDGER",
                "file_ids": [item.get("id") for item in ledgers],
            }
        )
    elif len(ledgers) == 1:
        try:
            runtime["prior_ledger"] = _download_json(reader_api, ledgers[0]["id"])
            runtime["prior_ledger_file"] = {
                "id": ledgers[0].get("id"),
                "name": ledgers[0].get("name"),
                "modifiedTime": ledgers[0].get("modifiedTime"),
            }
        except Exception as exc:
            runtime["status"] = "SEMANTIC_STATE_RECONCILIATION_REQUIRED"
            runtime["holds"].append(
                {
                    "reason": "PERSISTENT_SEMANTIC_LEDGER_UNREADABLE",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    checkpoint_items = [
        item
        for item in items
        if item.get("mimeType") != FOLDER_MIME
        and str(item.get("name") or "").endswith("__CHECKPOINT_CURRENT.json")
    ]
    for item in checkpoint_items:
        try:
            checkpoint = _download_json(reader_api, item["id"])
            runtime["checkpoint_snapshots"].append(
                _checkpoint_projection(checkpoint, file_meta=item)
            )
        except Exception as exc:
            runtime["status"] = "SEMANTIC_STATE_RECONCILIATION_REQUIRED"
            runtime["holds"].append(
                {
                    "reason": "SEMANTIC_CHECKPOINT_UNREADABLE",
                    "file_id": item.get("id"),
                    "file_name": item.get("name"),
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    runtime["checkpoint_snapshots"].sort(
        key=lambda row: (
            str(row.get("source_name") or ""),
            str(row.get("current_trading_date") or ""),
            str(row.get("checkpoint_modified_time") or ""),
            str(row.get("checkpoint_file_id") or ""),
        )
    )
    runtime["fingerprint"] = semantic_runtime_fingerprint(runtime)
    return runtime


def semantic_runtime_fingerprint(runtime: dict | None) -> str:
    runtime = runtime or {}
    checkpoints = []
    for row in runtime.get("checkpoint_snapshots") or []:
        checkpoints.append(
            {
                "checkpoint_file_id": row.get("checkpoint_file_id"),
                "checkpoint_file_name": row.get("checkpoint_file_name"),
                "checkpoint_modified_time": row.get("checkpoint_modified_time"),
                "source_drive_id": row.get("source_drive_id"),
                "source_sha256": row.get("source_sha256"),
                "semantic_generation_id": row.get("semantic_generation_id"),
                "semantic_state": row.get("semantic_state"),
                "current_trading_date": row.get("current_trading_date"),
                "completed_ticker_context_paths": row.get("completed_ticker_context_paths"),
                "remaining_ticker_context_paths": row.get("remaining_ticker_context_paths"),
                "next_exact_resume_point": row.get("next_exact_resume_point"),
                "open_carry_count": row.get("open_carry_count"),
            }
        )
    prior = runtime.get("prior_ledger")
    prior_projection = None
    if isinstance(prior, dict):
        prior_projection = {
            "schema": prior.get("schema"),
            "generation_id": prior.get("generation_id"),
            "semantic_contract_fingerprint": prior.get("semantic_contract_fingerprint"),
            "updated_at_utc": prior.get("updated_at_utc"),
            "sources": prior.get("sources") or {},
        }
    return _fingerprint(
        {
            "status": runtime.get("status"),
            "holds": runtime.get("holds") or [],
            "prior_ledger": prior_projection,
            "checkpoints": checkpoints,
        }
    )


def _checkpoint_by_source(runtime: dict) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for row in runtime.get("checkpoint_snapshots") or []:
        source_id = str(row.get("source_drive_id") or "")
        if source_id:
            grouped.setdefault(source_id, []).append(row)
    return {
        source_id: max(
            rows,
            key=lambda row: (
                str(row.get("checkpoint_modified_time") or ""),
                str(row.get("current_trading_date") or ""),
                str(row.get("checkpoint_file_id") or ""),
            ),
        )
        for source_id, rows in grouped.items()
    }


def _classification_action_by_id(classification: dict) -> dict[str, str]:
    actions: dict[str, str] = {}
    for key, action in (
        ("verified_unchanged", "VERIFIED_UNCHANGED"),
        ("new_processed", "NEW"),
        ("changed_rebuilt", "CHANGED"),
        ("replacement_same_content", "REPLACEMENT_SAME_CONTENT"),
    ):
        for row in classification.get(key, []) or []:
            source_id = str(row.get("source_drive_id") or "")
            if source_id:
                actions[source_id] = action
    return actions


def _base_state(source: dict, data_state: str) -> dict:
    return {
        "source_drive_id": source.get("source_drive_id"),
        "source_name": source.get("source_name"),
        "source_sha256": source.get("source_sha256"),
        "source_mode": "HISTORICAL_REPLAY",
        "data_state": data_state,
        "semantic_state": "UNKNOWN_NEEDS_RECONCILIATION",
        "semantic_generation_id": FROZEN_GENERATION_ID,
        "semantic_contract_fingerprint": SEMANTIC_CONTRACT_FINGERPRINT,
        "current_trading_date": None,
        "completed_dates": [],
        "completed_ticker_context_paths": None,
        "total_ticker_context_paths": None,
        "remaining_ticker_context_paths": None,
        "last_verified_source_record": None,
        "last_verified_source_timestamp": None,
        "next_exact_resume_point": None,
        "event_journey_count": None,
        "observation_count": None,
        "open_carry_count": None,
        "cross_ticker_reconciliation_state": "UNKNOWN",
        "cross_date_open_journey_carry_state": "REQUIRED_BY_METHOD",
        "cross_month_atlas_reconciliation_state": "PENDING_OR_UNKNOWN",
        "stale_reopen_reason": None,
        "stale_reopen_scope": None,
        "hold": None,
        "checkpoint_provenance": None,
        "prior_causal_provenance_preserved": True,
    }


def _apply_checkpoint(state: dict, checkpoint: dict, source: dict) -> dict:
    state = dict(state)
    state.update(
        {
            "source_mode": checkpoint.get("source_mode") or state.get("source_mode"),
            "semantic_state": checkpoint.get("semantic_state") or "UNKNOWN_NEEDS_RECONCILIATION",
            "semantic_generation_id": checkpoint.get("semantic_generation_id"),
            "current_trading_date": checkpoint.get("current_trading_date"),
            "completed_ticker_context_paths": checkpoint.get("completed_ticker_context_paths"),
            "total_ticker_context_paths": checkpoint.get("total_ticker_context_paths"),
            "remaining_ticker_context_paths": checkpoint.get("remaining_ticker_context_paths"),
            "last_verified_source_record": checkpoint.get("last_verified_source_record"),
            "last_verified_source_timestamp": checkpoint.get("last_verified_source_timestamp"),
            "next_exact_resume_point": checkpoint.get("next_exact_resume_point"),
            "event_journey_count": checkpoint.get("event_journey_count"),
            "observation_count": checkpoint.get("observation_count"),
            "open_carry_count": checkpoint.get("open_carry_count"),
            "cross_ticker_reconciliation_state": checkpoint.get("cross_ticker_reconciliation_state") or "UNKNOWN",
            "checkpoint_provenance": {
                "checkpoint_id": checkpoint.get("checkpoint_id"),
                "file_id": checkpoint.get("checkpoint_file_id"),
                "file_name": checkpoint.get("checkpoint_file_name"),
                "modified_time": checkpoint.get("checkpoint_modified_time"),
                "checkpoint_status": checkpoint.get("checkpoint_status"),
                "rubric_version": checkpoint.get("rubric_version"),
            },
        }
    )
    checkpoint_sha = checkpoint.get("source_sha256")
    if checkpoint_sha and source.get("source_sha256") and checkpoint_sha != source.get("source_sha256"):
        state["semantic_state"] = "STALE_REQUIRES_REVALIDATION"
        state["stale_reopen_reason"] = "SEMANTIC_CHECKPOINT_SOURCE_HASH_MISMATCH"
        state["stale_reopen_scope"] = "DEPENDENCY_AFFECTED_SCOPE_PLUS_REQUIRED_BOUNDARY_CONTEXT"
    generation = checkpoint.get("semantic_generation_id")
    if generation and generation != FROZEN_GENERATION_ID:
        state["semantic_state"] = "STALE_REQUIRES_REVALIDATION"
        state["stale_reopen_reason"] = "SEMANTIC_GENERATION_MISMATCH"
        state["stale_reopen_scope"] = "DEPENDENCY_AFFECTED_SCOPE_PLUS_REQUIRED_BOUNDARY_CONTEXT"
    return state


def _apply_prior(state: dict, prior: dict, source: dict) -> dict:
    merged = dict(prior)
    merged.update(
        {
            "source_drive_id": source.get("source_drive_id"),
            "source_name": source.get("source_name"),
            "source_sha256": source.get("source_sha256"),
            "data_state": state.get("data_state"),
            "semantic_contract_fingerprint": SEMANTIC_CONTRACT_FINGERPRINT,
            "prior_causal_provenance_preserved": True,
        }
    )
    if prior.get("source_sha256") != source.get("source_sha256"):
        merged["semantic_state"] = "STALE_REQUIRES_REVALIDATION"
        merged["stale_reopen_reason"] = "ACTIVE_SOURCE_HASH_CHANGED"
        merged["stale_reopen_scope"] = "DEPENDENCY_AFFECTED_SCOPE_PLUS_REQUIRED_BOUNDARY_CONTEXT"
    return merged


def _apply_data_transition(state: dict, data_state: str) -> dict:
    state = dict(state)
    if data_state == "NEW":
        if state.get("semantic_state") == "UNKNOWN_NEEDS_RECONCILIATION":
            state["semantic_state"] = "NOT_STARTED"
        state["stale_reopen_reason"] = state.get("stale_reopen_reason") or "NEW_SOURCE"
        state["stale_reopen_scope"] = state.get("stale_reopen_scope") or "FULL_SOURCE_SEMANTIC_READ_PLUS_REQUIRED_BOUNDARY_CONTEXT"
    elif data_state in {"CHANGED", "REPLACEMENT_SAME_CONTENT"}:
        state["semantic_state"] = "STALE_REQUIRES_REVALIDATION"
        state["stale_reopen_reason"] = data_state
        state["stale_reopen_scope"] = "DEPENDENCY_AFFECTED_SCOPE_PLUS_REQUIRED_BOUNDARY_CONTEXT"
        state["prior_causal_provenance_preserved"] = True
    return state


def _work_item(state: dict) -> dict | None:
    semantic_state = str(state.get("semantic_state") or "")
    base = {
        "source_drive_id": state.get("source_drive_id"),
        "source_name": state.get("source_name"),
        "source_sha256": state.get("source_sha256"),
        "source_mode": state.get("source_mode"),
        "data_state": state.get("data_state"),
        "semantic_state": semantic_state,
        "current_trading_date": state.get("current_trading_date"),
        "next_exact_resume_point": state.get("next_exact_resume_point"),
        "open_carry_count": state.get("open_carry_count"),
        "cross_ticker_reconciliation_state": state.get("cross_ticker_reconciliation_state"),
        "cross_date_open_journey_carry_state": state.get("cross_date_open_journey_carry_state"),
        "cross_month_atlas_reconciliation_state": state.get("cross_month_atlas_reconciliation_state"),
        "stale_reopen_reason": state.get("stale_reopen_reason"),
        "stale_reopen_scope": state.get("stale_reopen_scope"),
        "checkpoint_provenance": state.get("checkpoint_provenance"),
    }
    if semantic_state == "COMPLETE":
        return None
    if semantic_state == "NOT_STARTED":
        return {**base, "work_kind": "START_REQUIRED_SEMANTIC_SCOPE", "required_scope": state.get("stale_reopen_scope") or "FULL_SOURCE_SEMANTIC_READ_PLUS_REQUIRED_BOUNDARY_CONTEXT"}
    if semantic_state in {"IN_PROGRESS", "PARTIAL", "DATE_OPEN", "QUEUED", "BACKLOGGED", "LAGGING"}:
        return {**base, "work_kind": "RESUME_EXACT_SEMANTIC_CHECKPOINT", "required_scope": "UNFINISHED_SCOPE_FROM_EXACT_CHECKPOINT"}
    if semantic_state == "WAITING_RECONCILIATION":
        return {**base, "work_kind": "RUN_REQUIRED_SEMANTIC_RECONCILIATION", "required_scope": "CROSS_TICKER_DATE_OPEN_CARRY_AND_ATLAS_AS_APPLICABLE"}
    if semantic_state == "STALE_REQUIRES_REVALIDATION":
        return {**base, "work_kind": "SCOPED_REVALIDATION_OR_REREAD", "required_scope": state.get("stale_reopen_scope") or "DEPENDENCY_AFFECTED_SCOPE_PLUS_REQUIRED_BOUNDARY_CONTEXT"}
    if semantic_state == "HOLD":
        return {**base, "work_kind": "HOLD", "required_scope": "STOP_AFFECTED_SEMANTIC_PROMOTION", "hold": state.get("hold")}
    return {
        **base,
        "work_kind": "RECONCILE_SEMANTIC_STATE_BEFORE_READING",
        "required_scope": "RESOLVE_AUTHORITATIVE_SEMANTIC_COMPLETION_AND_RESUME_STATE; DO_NOT_ASSUME_COMPLETE_OR_RESTART",
    }


def _source_watermark(active_sources: list[dict]) -> dict | None:
    candidates = [
        row
        for row in active_sources
        if row.get("last_observed_date") or row.get("last_observed_time")
    ]
    if not candidates:
        return None
    row = max(
        candidates,
        key=lambda item: (
            str(item.get("last_observed_date") or ""),
            str(item.get("last_observed_time") or ""),
            str(item.get("source_name") or ""),
        ),
    )
    return {
        "trading_date": row.get("last_observed_date"),
        "event_time": row.get("last_observed_time"),
        "source_drive_id": row.get("source_drive_id"),
        "source_name": row.get("source_name"),
        "precision": "SOURCE_COVERAGE_WATERMARK",
    }


def build_semantic_controls(
    *,
    active_sources: list[dict],
    classification: dict,
    semantic_delta_queue: dict,
    semantic_runtime: dict | None,
    updated_at_utc: str,
    external_watermarks: dict | None = None,
    auxiliary_triggers: list[dict] | None = None,
) -> dict:
    """Build semantic ledger + authoritative work queue, never semantic conclusions."""
    runtime = semantic_runtime or {
        "schema": SEMANTIC_RUNTIME_SCHEMA,
        "status": "SEMANTIC_STATE_RECONCILIATION_REQUIRED",
        "prior_ledger": None,
        "checkpoint_snapshots": [],
        "holds": [{"reason": "SEMANTIC_RUNTIME_NOT_PROVIDED"}],
    }
    prior_sources = {
        str(key): dict(value)
        for key, value in ((runtime.get("prior_ledger") or {}).get("sources") or {}).items()
    }
    checkpoints = _checkpoint_by_source(runtime)
    action_by_id = _classification_action_by_id(classification)
    source_states: dict[str, dict] = {}

    for source in _chronological_sources(active_sources):
        source_id = str(source.get("source_drive_id") or "")
        if not source_id:
            continue
        data_state = action_by_id.get(
            source_id, str(source.get("delta_action") or "VERIFIED_UNCHANGED")
        )
        state = _base_state(source, data_state)
        if source_id in checkpoints:
            state = _apply_checkpoint(state, checkpoints[source_id], source)
        elif source_id in prior_sources:
            state = _apply_prior(state, prior_sources[source_id], source)
        elif data_state == "NEW":
            state["semantic_state"] = "NOT_STARTED"
        state = _apply_data_transition(state, data_state)
        source_states[source_id] = state

    inactive_sources = []
    for row in classification.get("removed_purged", []) or []:
        source_id = str(row.get("source_drive_id") or "")
        prior = prior_sources.get(source_id, {})
        inactive_sources.append(
            {
                "source_drive_id": source_id,
                "source_name": row.get("source_name") or prior.get("source_name"),
                "source_sha256": row.get("source_sha256") or prior.get("source_sha256"),
                "semantic_state": "INACTIVE_SOURCE_REMOVED",
                "invalidation_required": True,
                "invalidation_scope": "ACTIVE_SEMANTIC_OBJECTS_AND_ATLAS_MEMBERSHIP_FOR_REMOVED_SOURCE",
                "canonical_raw_delete_authorized": False,
                "prior_causal_provenance_preserved": True,
            }
        )

    work_items = []
    for source in _chronological_sources(list(source_states.values())):
        item = _work_item(source)
        if item is not None:
            work_items.append(item)
    for row in inactive_sources:
        work_items.append(
            {
                **row,
                "work_kind": "INVALIDATE_REMOVED_SOURCE_FROM_ACTIVE_SEMANTIC_STATE",
                "required_scope": row["invalidation_scope"],
            }
        )
    for trigger in auxiliary_triggers or []:
        work_items.append(
            {
                "work_kind": "SCOPED_AUXILIARY_EVIDENCE_RECONCILIATION",
                "trigger": trigger,
                "causality_rule": "PRESERVE_ACTUAL_AVAILABILITY_KNOWN_AT_TIME; NO_BACKDATING",
            }
        )

    external_watermarks = external_watermarks or {}
    data_watermark = _source_watermark(active_sources)
    checkpoint_updates = [
        str(row.get("checkpoint_modified_time"))
        for row in runtime.get("checkpoint_snapshots") or []
        if row.get("checkpoint_modified_time")
    ]
    explicit_semantic_times = [
        str(row.get("last_verified_source_timestamp"))
        for row in source_states.values()
        if row.get("last_verified_source_timestamp")
    ]
    if runtime.get("holds"):
        scheduler_status = "SEMANTIC_STATE_RECONCILIATION_REQUIRED"
        backlog_state = "PARTIAL_RECONCILIATION_REQUIRED"
    elif work_items:
        scheduler_status = "WORK_PENDING"
        backlog_state = "BACKLOGGED"
    else:
        scheduler_status = "NO_PENDING_SEMANTIC_WORK_FOR_DISCOVERED_SCOPE"
        backlog_state = "CURRENT_FOR_DISCOVERED_GOVERNED_SCOPE"

    ledger = {
        "schema": SEMANTIC_LEDGER_SCHEMA,
        "generation_id": FROZEN_GENERATION_ID,
        "semantic_contract_id": SEMANTIC_CONTRACT_ID,
        "semantic_contract_fingerprint": SEMANTIC_CONTRACT_FINGERPRINT,
        "updated_at_utc": updated_at_utc,
        "scheduler_status": scheduler_status,
        "data_plane_state_is_not_semantic_completion": True,
        "semantic_reader_is_not_latency_critical_production_signal_loop": True,
        "source_count_is_not_an_invariant": True,
        "runtime_input_status": runtime.get("status"),
        "runtime_input_holds": runtime.get("holds") or [],
        "runtime_input_fingerprint": runtime.get("fingerprint") or semantic_runtime_fingerprint(runtime),
        "watermarks": {
            "capture_watermark": external_watermarks.get("capture_watermark") or data_watermark,
            "data_plane_accepted_watermark": external_watermarks.get("data_plane_watermark") or data_watermark,
            "semantic_market_event_watermark": max(explicit_semantic_times) if explicit_semantic_times else None,
            "semantic_checkpoint_updated_at_utc": max(checkpoint_updates) if checkpoint_updates else None,
            "backlog_state": backlog_state,
            "feed_freshness": external_watermarks.get("feed_freshness", "NOT_APPLICABLE_HISTORICAL_REPLAY"),
        },
        "sources": source_states,
        "inactive_sources": inactive_sources,
        "late_eod_policy": {
            "allowed_inputs": [
                "BROKER_PARTICIPANT_SUMMARY",
                "NFSS_NBSS_PROVIDER_EQUIVALENT",
                "FOREIGN_FLOW",
                "CLOSING_POSTCLOSE",
                "CORRECTION_BACKFILL",
                "IMAGE_DERIVED_EVIDENCE",
            ],
            "known_at_required": True,
            "backdating_prohibited": True,
            "hindsight_complete_update_allowed": True,
        },
        "image_auxiliary_evidence_policy": {
            "separate_governed_ingestion_adapter": True,
            "structured_provider_data_primary_when_proven_equivalent": True,
            "image_derived_requires_provenance_confidence_validation": True,
            "alternate_analytical_engine": False,
        },
    }
    work_queue = {
        "schema": SEMANTIC_WORK_QUEUE_SCHEMA,
        "generation_id": FROZEN_GENERATION_ID,
        "semantic_contract_fingerprint": SEMANTIC_CONTRACT_FINGERPRINT,
        "created_at_utc": updated_at_utc,
        "scheduler_status": scheduler_status,
        "queue_role": "AUTHORITATIVE_SEMANTIC_WORK_SCHEDULER_OUTPUT; INDEPENDENT_FROM_DATA_DELTA_COMPLETION",
        "data_change_trigger_input": semantic_delta_queue,
        "work_item_count": len(work_items),
        "work_items": work_items,
        "rules": {
            "verified_unchanged_complete": "NO_FULL_REREAD",
            "verified_unchanged_in_progress": "RESUME_EXACT_SEMANTIC_CHECKPOINT",
            "verified_unchanged_not_started": "SCHEDULE_REQUIRED_SEMANTIC_WORK",
            "new": "DATA_PLANE_FIRST_THEN_FULL_SEMANTIC_SCOPE",
            "changed_or_replaced": "SCOPED_DEPENDENCY_REVALIDATION_PRESERVE_PRIOR_CAUSAL_PROVENANCE",
            "removed": "INVALIDATE_ACTIVE_SEMANTIC_MEMBERSHIP_NO_RAW_DELETE",
            "hold": "STOP_AFFECTED_DOWNSTREAM_PROMOTION_AND_PERSIST_RESUME",
            "late_eod": "RECONCILE_AT_ACTUAL_AVAILABILITY_TIME_NO_BACKDATING",
            "semantic_lag": "EXPOSE_BACKLOG_DO_NOT_STOP_AUTHORIZED_LOSSLESS_CAPTURE",
        },
        "realtime_readiness": {
            "capture_state_separate": True,
            "canonical_current_state_separate": True,
            "semantic_research_state_separate": True,
            "post_session_eod_reconciliation_separate": True,
            "production_result_state_separate": True,
            "semantic_ai_in_latency_critical_signal_loop": False,
        },
    }
    return {
        "PERSISTENT_SEMANTIC_RESEARCH_STATE.json": ledger,
        "AI_SEMANTIC_WORK_QUEUE.json": work_queue,
    }
