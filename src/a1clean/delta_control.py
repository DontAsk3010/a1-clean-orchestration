from __future__ import annotations

from pathlib import Path

from .config import FROZEN_GENERATION_ID, FROZEN_IMPL_VERSION, FROZEN_RAW_FOLDER_DRIVE_ID
from .delta_state import source_row_by_id
from .semantic_work import build_semantic_controls


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


def _manifest_to_persistent_state(
    manifest: dict,
    prior: dict | None,
    *,
    accepted_at_utc: str,
) -> dict:
    state = {
        "source_drive_id": manifest.get("source_drive_id"),
        "source_name": manifest.get("source_name"),
        "source_size_bytes": manifest.get("source_size_bytes"),
        "source_modified_time": manifest.get("source_modified_time"),
        "source_sha256": manifest.get("source_sha256"),
        "status": manifest.get("status"),
        "physical_shard_count": manifest.get("physical_shard_count"),
        "semantic_bundle_count": manifest.get("semantic_bundle_count"),
        "source_data_rows": manifest.get("source_data_rows"),
        "routed_rows": manifest.get("routed_rows"),
        "unresolved_routing_rows": manifest.get("unresolved_routing_rows"),
        "unique_trading_dates": manifest.get("unique_trading_dates"),
        "unique_tickers": manifest.get("unique_tickers"),
        "ticker_day_objects": manifest.get("ticker_day_objects"),
        "first_observed_date": manifest.get("first_observed_date"),
        "first_observed_time": manifest.get("first_observed_time"),
        "last_observed_date": manifest.get("last_observed_date"),
        "last_observed_time": manifest.get("last_observed_time"),
        "generation_id": manifest.get("generation_id"),
        "data_plane_impl_version": manifest.get("data_plane_impl_version"),
        "accepted_at_utc": accepted_at_utc,
    }
    if prior is not None and "bootstrap_from_prior_success" in prior:
        state["bootstrap_from_prior_success"] = prior.get("bootstrap_from_prior_success")
    return state


def _semantic_reopen_rows(
    changed_sources: list[dict],
    active_sources: list[dict],
    *,
    reason_by_id: dict[str, str],
) -> list[dict]:
    ordered = _chronological_sources(active_sources)
    index = {
        str(row.get("source_drive_id")): pos
        for pos, row in enumerate(ordered)
    }
    out: list[dict] = []
    for row in _chronological_sources(changed_sources):
        source_id = str(row.get("source_drive_id"))
        pos = index.get(source_id)
        previous_name = (
            ordered[pos - 1].get("source_name")
            if pos is not None and pos > 0
            else None
        )
        next_name = (
            ordered[pos + 1].get("source_name")
            if pos is not None and pos + 1 < len(ordered)
            else None
        )
        out.append(
            {
                "source_drive_id": source_id,
                "source_name": row.get("source_name"),
                "reason": reason_by_id.get(source_id, "CHANGED"),
                "required_scope": "FULL_SOURCE_SEMANTIC_READ_PLUS_REQUIRED_BOUNDARY_CONTEXT",
                "previous_source_context": previous_name,
                "next_source_context": next_name,
                "boundary_rule": (
                    "Adjacent accepted source is reopened only as required RAW/context carry; "
                    "unchanged source is not blindly reread in full."
                ),
            }
        )
    return out


def _delta_public(
    rows: list[dict],
    processed: dict[str, dict],
    *,
    include_stats: bool = False,
) -> list[dict]:
    output = []
    for row in rows:
        item = {
            "source_drive_id": row.get("source_drive_id"),
            "source_name": row.get("source_name"),
            "source_sha256": row.get("source_sha256"),
        }
        if include_stats:
            processed_row = processed.get(str(row.get("source_drive_id")), {})
            manifest = processed_row.get("source_manifest") or {}
            item.update(
                {
                    "source_data_rows": manifest.get("source_data_rows"),
                    "ticker_day_objects": manifest.get("ticker_day_objects"),
                    "semantic_bundle_count": manifest.get("semantic_bundle_count"),
                }
            )
        output.append(item)
    return output


def build_control_bundle(
    *,
    baseline_global: dict,
    baseline_persistent: dict,
    preflight: dict,
    classification: dict,
    processed: dict[str, dict],
    started_at_utc: str,
    finished_at_utc: str,
    refresh_id: str,
    semantic_runtime: dict | None = None,
) -> dict:
    """Build governed data-plane controls plus independent semantic work controls.

    Unchanged source artifacts are reused by reference. NEW/CHANGED/replacement
    source manifests come from the frozen V2 source processor, not from new
    analytical logic. Semantic completion is tracked independently from source
    delta classification; this function schedules work but performs no semantic
    interpretation and creates no behavior labels.
    """

    if classification.get("holds"):
        raise RuntimeError("DELTA_MACHINE_CONTROL_BUNDLE_BLOCKED_BY_HOLD")

    prior_sources = {
        str(row.get("source_drive_id")): dict(row)
        for row in baseline_global.get("sources", [])
    }
    persistent_prior = {
        str(key): dict(value)
        for key, value in (baseline_persistent.get("sources") or {}).items()
    }

    superseded_ids = {
        str(row.get("source_drive_id"))
        for row in classification.get("removed_purged", [])
        if row.get("source_drive_id")
    }
    superseded_ids.update(
        str(row.get("previous_source_drive_id"))
        for key in ("changed_rebuilt", "replacement_same_content")
        for row in classification.get(key, [])
        if row.get("previous_source_drive_id")
    )

    active_by_id = {
        source_id: row
        for source_id, row in prior_sources.items()
        if source_id not in superseded_ids
    }
    persistent_by_id = {
        source_id: row
        for source_id, row in persistent_prior.items()
        if source_id not in superseded_ids
    }

    runtime_root = str(baseline_global.get("runtime_root") or "").rstrip("/\\")
    for source_id, row in processed.items():
        manifest = dict(row["source_manifest"])
        manifest["delta_action"] = row.get("delta_action")
        if runtime_root and manifest.get("source_name"):
            stem = Path(str(manifest["source_name"])).stem
            manifest["market_day_index"] = (
                runtime_root
                + "/03_MARKET_DAY_INDEX/"
                + stem
                + "__MARKET_DAY_INDEX.json"
            )
        active_by_id[source_id] = manifest
        persistent_by_id[source_id] = _manifest_to_persistent_state(
            manifest,
            persistent_prior.get(source_id),
            accepted_at_utc=finished_at_utc,
        )

    # A new refresh reclassifies every still-active unchanged source as
    # VERIFIED_UNCHANGED. Do not carry a prior run's NEW/CHANGED action forward.
    for row in classification.get("verified_unchanged", []):
        source_id = str(row.get("source_drive_id"))
        if source_id in active_by_id:
            active_by_id[source_id] = dict(active_by_id[source_id])
            active_by_id[source_id]["delta_action"] = "VERIFIED_UNCHANGED"

    active_sources = _chronological_sources(list(active_by_id.values()))
    if len(active_sources) != classification.get("active_source_count"):
        raise RuntimeError(
            "DELTA_MACHINE_ACTIVE_SOURCE_CARDINALITY_MISMATCH: "
            f"control={len(active_sources)} canonical={classification.get('active_source_count')}"
        )

    semantic_gate = "READY_FOR_AI_DELTA"
    global_manifest = dict(baseline_global)
    global_manifest.update(
        {
            "generation_id": FROZEN_GENERATION_ID,
            "data_plane_impl_version": FROZEN_IMPL_VERSION,
            "created_at_utc": finished_at_utc,
            "canonical_source_home_drive_id": FROZEN_RAW_FOLDER_DRIVE_ID,
            "sources": active_sources,
            "delta_refresh_id": refresh_id,
            "delta_semantic_gate": semantic_gate,
            "physical_source_loss_allowed": False,
            "unknown_field_drop_allowed": False,
            "verified_unchanged_source_reuse": True,
            "new_changed_only_full_processing": True,
            "semantic_reader_status": "NOT_RUN_BY_THIS_NOTEBOOK",
            "behavior_event_journey_pass_status": "NOT_EVALUATED_BY_THIS_NOTEBOOK",
            "data_plane_state_is_not_semantic_completion": True,
            "semantic_work_state_file": "PERSISTENT_SEMANTIC_RESEARCH_STATE.json",
            "semantic_work_queue_file": "AI_SEMANTIC_WORK_QUEUE.json",
        }
    )

    persistent_state = {
        "state_version": baseline_persistent.get("state_version", 1),
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "updated_at_utc": finished_at_utc,
        "sources": persistent_by_id,
    }

    preflight_rows = source_row_by_id(preflight)
    discovery_files = []
    for source_id in sorted(
        preflight_rows,
        key=lambda sid: str(preflight_rows[sid].get("name")),
    ):
        row = preflight_rows[source_id]
        discovery_files.append(
            {
                "drive_file_id": source_id,
                "name": row.get("name"),
                "mime_type": row.get("drive_mime_type") or "text/csv",
                "drive_size_bytes": row.get("drive_size"),
                "modified_time": row.get("drive_modified_time"),
                "local_path": row.get("local_path"),
                "local_size_bytes": row.get("local_size"),
                "identity_state": (
                    "MATCH"
                    if row.get("status") == "PASS_EXACT_MD5"
                    else row.get("status")
                ),
            }
        )
    source_discovery = {
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_home_drive_id": FROZEN_RAW_FOLDER_DRIVE_ID,
        "files": discovery_files,
    }

    coverage = {
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "sources_in_chronological_coverage_order": [
            {
                "source_drive_id": row.get("source_drive_id"),
                "source_name": row.get("source_name"),
                "source_sha256": row.get("source_sha256"),
                "first_observed_date": row.get("first_observed_date"),
                "first_observed_time": row.get("first_observed_time"),
                "last_observed_date": row.get("last_observed_date"),
                "last_observed_time": row.get("last_observed_time"),
                "source_data_rows": row.get("source_data_rows"),
                "ticker_day_objects": row.get("ticker_day_objects"),
                "market_day_index": row.get("market_day_index"),
            }
            for row in active_sources
        ],
    }

    reason_by_id = {
        str(row["source_drive_id"]): reason
        for key, reason in (
            ("new_processed", "NEW"),
            ("changed_rebuilt", "CHANGED"),
            ("replacement_same_content", "REPLACEMENT_SAME_CONTENT"),
        )
        for row in classification.get(key, [])
    }
    reopened_ids = set(reason_by_id)
    reopened_sources = [
        row
        for row in active_sources
        if str(row.get("source_drive_id")) in reopened_ids
    ]
    semantic_reopen = _semantic_reopen_rows(
        reopened_sources,
        active_sources,
        reason_by_id=reason_by_id,
    )
    removed_semantic = [
        {
            "source_drive_id": row.get("source_drive_id"),
            "source_name": row.get("source_name"),
            "source_sha256": row.get("source_sha256"),
        }
        for row in classification.get("removed_purged", [])
    ]
    semantic_queue = {
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "created_at_utc": finished_at_utc,
        "semantic_gate": semantic_gate,
        "queue_role": "DATA_CHANGE_TRIGGER_ONLY_NOT_SEMANTIC_COMPLETION_AUTHORITY",
        "full_semantic_sources": semantic_reopen,
        "removed_sources_invalidate_prior_semantic_objects": removed_semantic,
        "cross_ticker_reconciliation_required": True,
        "cross_date_open_journey_carry_required": True,
        "cross_month_atlas_reconciliation_required": True,
        "unchanged_source_policy": (
            "DO_NOT_FULL_REREAD_SOLELY_FOR_DATA_DELTA; AUTHORITATIVE_SEMANTIC_WORK_QUEUE_MAY_STILL_REQUIRE_RESUME_OR_RECONCILIATION"
        ),
    }

    delta_refresh = {
        "refresh_id": refresh_id,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "started_at_utc": started_at_utc,
        "bootstrap_source_count": 0,
        "verified_unchanged": _delta_public(
            classification.get("verified_unchanged", []), processed
        ),
        "new_processed": _delta_public(
            classification.get("new_processed", []), processed, include_stats=True
        ),
        "changed_rebuilt": _delta_public(
            classification.get("changed_rebuilt", []), processed, include_stats=True
        ),
        "removed_purged": _delta_public(
            classification.get("removed_purged", []), processed
        ),
        "replacement_same_content": _delta_public(
            classification.get("replacement_same_content", []),
            processed,
            include_stats=True,
        ),
        "holds": [],
        "semantic_reopen_required": semantic_reopen,
        "finished_at_utc": finished_at_utc,
        "semantic_gate": semantic_gate,
        "active_source_count": len(active_sources),
        "data_plane_state_is_not_semantic_completion": True,
    }

    semantic_controls = build_semantic_controls(
        active_sources=active_sources,
        classification=classification,
        semantic_delta_queue=semantic_queue,
        semantic_runtime=semantic_runtime,
        updated_at_utc=finished_at_utc,
    )

    return {
        "GLOBAL_DATA_PLANE_MANIFEST.json": global_manifest,
        "GLOBAL_SOURCE_DISCOVERY.json": source_discovery,
        "GLOBAL_SOURCE_COVERAGE_INDEX.json": coverage,
        "PERSISTENT_SOURCE_STATE.json": persistent_state,
        "LATEST_DELTA_REFRESH.json": delta_refresh,
        "AI_SEMANTIC_DELTA_QUEUE.json": semantic_queue,
        **semantic_controls,
    }
