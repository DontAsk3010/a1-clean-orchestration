from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Mapping, Sequence


OWNER_FULL_DEPTH_DEFINITION_VERSION = "A1_M2_OWNER_FULL_DEPTH_20261001_V1"


def _parse_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip().replace("Z", "+00:00")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _elapsed_seconds(a: Any, b: Any) -> float | None:
    left = _parse_ts(a)
    right = _parse_ts(b)
    if left is None or right is None:
        return None
    return (right - left).total_seconds()


def _derived_rows(obj: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(x) for x in (obj.get("continuous_current_enrichment") or {}).get("derived_observations", [])]


def _source_parent(obj: Mapping[str, Any], *, start_index: int | None = None, end_index: int | None = None) -> dict[str, Any]:
    source_ref = dict(obj.get("source_ref") or {})
    rows = _derived_rows(obj)
    start_row = rows[start_index] if isinstance(start_index, int) and 0 <= start_index < len(rows) else None
    end_row = rows[end_index] if isinstance(end_index, int) and 0 <= end_index < len(rows) else None
    return {
        "source_name": source_ref.get("source_name"),
        "source_drive_id": source_ref.get("source_drive_id"),
        "source_sha256": source_ref.get("source_sha256"),
        "generation_id": source_ref.get("generation_id"),
        "packet_fingerprint": source_ref.get("packet_fingerprint"),
        "source_row_first": None if start_row is None else start_row.get("source_row"),
        "source_row_last": None if end_row is None else end_row.get("source_row"),
        "timestamp_first": None if start_row is None else start_row.get("timestamp"),
        "timestamp_last": None if end_row is None else end_row.get("timestamp"),
    }


def build_state_maturity_and_revisit(obj: Mapping[str, Any]) -> dict[str, Any]:
    runs = [dict(x) for x in obj.get("state_runs", [])]
    seen: dict[str, list[int]] = defaultdict(list)
    records: list[dict[str, Any]] = []
    for ordinal, run in enumerate(runs, 1):
        key = str(run.get("state_key") or "UNKNOWN")
        start_index = int(run.get("start_index", -1))
        end_index = int(run.get("end_index", start_index))
        prior_ordinals = list(seen[key])
        recurrence_ordinal = len(prior_ordinals) + 1
        previous_same = prior_ordinals[-1] if prior_ordinals else None
        elapsed = _elapsed_seconds(run.get("start_timestamp"), run.get("end_timestamp"))
        records.append(
            {
                "run_ordinal": ordinal,
                "state_key": key,
                "start_index": start_index,
                "end_index": end_index,
                "start_timestamp": run.get("start_timestamp"),
                "end_timestamp": run.get("end_timestamp"),
                "persistence_actual_rows": int(run.get("row_count") or max(0, end_index - start_index + 1)),
                "elapsed_seconds_between_first_and_last_observation": elapsed,
                "recurrence_ordinal_for_same_state_key": recurrence_ordinal,
                "previous_same_state_run_ordinal": previous_same,
                "reappeared_after_other_state": previous_same is not None,
                "state_age_basis": "ACTUAL_SOURCE_OBSERVATION_ROWS_AND_TIMESTAMPS_ONLY",
                "maturity_interpretation": "NOT_FORCED_NO_OWNER_THRESHOLD",
                "decay_interpretation": "NOT_FORCED_NO_OWNER_THRESHOLD",
                "exhaustion_interpretation": "NOT_FORCED_NO_OWNER_THRESHOLD",
            }
        )
        seen[key].append(ordinal)
    return {
        "definition_version": OWNER_FULL_DEPTH_DEFINITION_VERSION,
        "run_count": len(records),
        "state_revisit_count": sum(max(0, len(v) - 1) for v in seen.values()),
        "distinct_state_key_count": len(seen),
        "records": records,
        "semantic_maturity_threshold_added": False,
    }


def build_attempt_retest_loop_topology(obj: Mapping[str, Any]) -> dict[str, Any]:
    rows = _derived_rows(obj)
    close_occurrences: dict[Any, list[int]] = defaultdict(list)
    close_revisits: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        close = (row.get("price_geometry") or {}).get("close")
        if close is None:
            continue
        prior = close_occurrences[close]
        if prior:
            close_revisits.append(
                {
                    "index": i,
                    "timestamp": row.get("timestamp"),
                    "source_row": row.get("source_row"),
                    "close_level": close,
                    "revisit_ordinal": len(prior) + 1,
                    "previous_same_close_index": prior[-1],
                    "actual_rows_since_previous_same_close": i - prior[-1],
                    "semantic_attack_defense_asserted": False,
                }
            )
        prior.append(i)
    continuous = dict(obj.get("continuous_current_enrichment") or {})
    primitive_attempts = dict(continuous.get("attempt_topology") or {})
    state = build_state_maturity_and_revisit(obj)
    return {
        "definition_version": OWNER_FULL_DEPTH_DEFINITION_VERSION,
        "primitive_attempt_counts": primitive_attempts,
        "close_level_revisit_count": len(close_revisits),
        "close_level_revisits": close_revisits,
        "state_revisit_count": state["state_revisit_count"],
        "nested_episode_semantics": "NOT_FORCED_WITHOUT_EVENT_SPECIFIC_SUPPORTED_DEFINITION",
        "attack_defense_semantics": "NOT_FORCED_WITHOUT_EVENT_SPECIFIC_SUPPORTED_DEFINITION",
        "retest_candidates_are_objective_revisits_not_automatic_semantic_labels": True,
    }


def build_lead_lag_graph(obj: Mapping[str, Any]) -> dict[str, Any]:
    rows = _derived_rows(obj)
    lanes = ("price", "volume", "value", "nbss", "range")
    events: dict[str, list[dict[str, Any]]] = {lane: [] for lane in lanes}
    for i, row in enumerate(rows):
        changes = dict(row.get("lead_lag_observation") or {})
        for lane in lanes:
            direction = str(changes.get(lane) or "UNKNOWN")
            if direction in {"UP", "DOWN"}:
                events[lane].append({"index": i, "timestamp": row.get("timestamp"), "direction": direction, "source_row": row.get("source_row")})
    pairs: list[dict[str, Any]] = []
    for left in lanes:
        for right in lanes:
            if left == right:
                continue
            le = events[left]
            re = events[right]
            if not le or not re:
                pairs.append({"from": left, "to": right, "status": "INSUFFICIENT_CHANGE_EVENTS"})
                continue
            first_left = le[0]
            first_right = re[0]
            if first_left["index"] < first_right["index"]:
                first_mover = left
            elif first_right["index"] < first_left["index"]:
                first_mover = right
            else:
                first_mover = "SAME_ACTUAL_OBSERVATION"
            pairs.append(
                {
                    "from": left,
                    "to": right,
                    "status": "AVAILABLE_OBJECTIVE_CHANGE_ORDER",
                    "first_from_event": first_left,
                    "first_to_event": first_right,
                    "first_mover": first_mover,
                    "lag_actual_rows": first_right["index"] - first_left["index"],
                    "lag_seconds": _elapsed_seconds(first_left["timestamp"], first_right["timestamp"]),
                    "from_change_event_count": len(le),
                    "to_change_event_count": len(re),
                    "causal_claim_beyond_observed_order_asserted": False,
                }
            )
    return {
        "definition_version": OWNER_FULL_DEPTH_DEFINITION_VERSION,
        "lane_change_events": events,
        "pairwise_first_change_order": pairs,
        "lead_lag_is_observed_temporal_order_not_causation": True,
    }


def build_data_quality_audit(obj: Mapping[str, Any]) -> dict[str, Any]:
    rows = _derived_rows(obj)
    duplicates: list[dict[str, Any]] = []
    out_of_order: list[dict[str, Any]] = []
    discontinuities: list[dict[str, Any]] = []
    previous_ts: datetime | None = None
    previous_raw: Any = None
    for i, row in enumerate(rows):
        raw_ts = row.get("timestamp")
        ts = _parse_ts(raw_ts)
        if i > 0 and ts is not None and previous_ts is not None:
            delta = (ts - previous_ts).total_seconds()
            if delta == 0:
                duplicates.append({"index": i, "timestamp": raw_ts, "previous_timestamp": previous_raw})
            elif delta < 0:
                out_of_order.append({"index": i, "timestamp": raw_ts, "previous_timestamp": previous_raw, "delta_seconds": delta})
            elif delta != 60:
                discontinuities.append({"index": i, "timestamp": raw_ts, "previous_timestamp": previous_raw, "delta_seconds": delta, "interpretation": "SESSION_RECESS_OR_SOURCE_GAP_NOT_INFERRED"})
        previous_ts = ts if ts is not None else previous_ts
        previous_raw = raw_ts
    return {
        "definition_version": OWNER_FULL_DEPTH_DEFINITION_VERSION,
        "duplicate_timestamp_count": len(duplicates),
        "duplicate_timestamps": duplicates,
        "out_of_order_timestamp_count": len(out_of_order),
        "out_of_order_timestamps": out_of_order,
        "timestamp_discontinuity_count": len(discontinuities),
        "timestamp_discontinuities": discontinuities,
        "stale": "UNKNOWN_UNPROVEN",
        "delayed": "UNKNOWN_UNPROVEN",
        "partial": "UNKNOWN_UNPROVEN",
        "reconnect": "UNKNOWN_UNPROVEN",
        "correction": "UNKNOWN_UNPROVEN",
        "clock_mismatch": "UNKNOWN_UNPROVEN",
        "schema_drift": "PROVEN_SEPARATELY_BY_SOURCE_PACKET_CONTRACT",
        "source_lane_disappearance": "UNKNOWN_UNPROVEN",
        "feed_issue": "UNKNOWN_UNPROVEN",
        "quality_is_not_market_behavior": True,
    }


def _lineage_common(obj: Mapping[str, Any], *, start_index: int | None, end_index: int | None) -> dict[str, Any]:
    return {
        "definition_version": OWNER_FULL_DEPTH_DEFINITION_VERSION,
        "source_parents": _source_parent(obj, start_index=start_index, end_index=end_index),
        "known_at_eligibility": "CAUSAL_SOURCE_POSITION_PRESERVED_BUT_BAR_COMPLETION_SEMANTICS_UNPROVEN",
        "availability": dict(obj.get("availability_registry") or {}),
        "uncertainty": {
            "known_at_bar_completion_semantics": "UNPROVEN",
            "missing_source_minutes_not_synthesized": True,
        },
    }


def attach_semantic_lineage(obj: dict[str, Any]) -> None:
    runs = [dict(x) for x in obj.get("state_runs", [])]
    for i, run in enumerate(runs):
        start = int(run.get("start_index", -1))
        end = int(run.get("end_index", start))
        run.update(
            {
                **_lineage_common(obj, start_index=start, end_index=end),
                "exact_time_or_range": {"start": run.get("start_timestamp"), "end": run.get("end_timestamp")},
                "derived_parents": {"state": dict(run.get("state") or {}), "state_key": run.get("state_key")},
                "reason_features": dict(run.get("state") or {}),
                "transition_lineage": {"previous_run_ordinal": i if i > 0 else None, "current_run_ordinal": i + 1, "next_run_ordinal": i + 2 if i + 1 < len(runs) else None},
            }
        )
    obj["state_runs"] = runs

    journeys = [dict(x) for x in obj.get("event_journeys", [])]
    lifecycle = [dict(x) for x in obj.get("behavior_lifecycle", [])]
    for i, journey in enumerate(journeys):
        start = dict(journey.get("causal_start") or {})
        start_index = start.get("index") if isinstance(start.get("index"), int) else None
        resolution = dict(journey.get("hindsight_resolution") or {})
        end_index = resolution.get("resolution_index") if isinstance(resolution.get("resolution_index"), int) else start_index
        life = lifecycle[i] if i < len(lifecycle) else {}
        journey.update(
            {
                **_lineage_common(obj, start_index=start_index, end_index=end_index),
                "exact_time_or_range": {"start": start.get("timestamp"), "end": resolution.get("resolution_timestamp"), "right_censored": bool(resolution.get("right_censored"))},
                "derived_parents": {"journey_kind": journey.get("journey_kind"), "lifecycle_journey_id": life.get("journey_id"), "formation_sequence": life.get("formation_sequence")},
                "reason_features": {"causal_start": start, "hindsight_resolution_kept_separate": True},
                "transition_lineage": {"journey_ordinal": i + 1, "lifecycle_journey_id": life.get("journey_id"), "temporal_connected_chain": life.get("temporal_connected_chain")},
            }
        )
    obj["event_journeys"] = journeys


def build_enriched_formation_snapshots(obj: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _derived_rows(obj)
    runs = [dict(x) for x in obj.get("state_runs", [])]
    journeys = [dict(x) for x in obj.get("event_journeys", [])]
    lifecycle = [dict(x) for x in obj.get("behavior_lifecycle", [])]
    out: list[dict[str, Any]] = []
    for i, journey in enumerate(journeys):
        start = dict(journey.get("causal_start") or {})
        idx = start.get("index") if isinstance(start.get("index"), int) else None
        derived = rows[idx] if isinstance(idx, int) and 0 <= idx < len(rows) else None
        covering_run = next((run for run in runs if isinstance(idx, int) and int(run.get("start_index", -1)) <= idx <= int(run.get("end_index", -1))), None)
        life = lifecycle[i] if i < len(lifecycle) else None
        out.append(
            {
                "definition_version": OWNER_FULL_DEPTH_DEFINITION_VERSION,
                "journey_ordinal": i + 1,
                "journey_kind": journey.get("journey_kind"),
                "causal_time_index": idx,
                "source_identity": dict(obj.get("source_ref") or {}),
                "available_rows_through_formation": None if idx is None else idx + 1,
                "primitive_and_continuous_derived_at_formation": derived,
                "state_run_at_formation": covering_run,
                "availability_at_formation": dict(obj.get("availability_registry") or {}),
                "context_at_formation": {
                    "source_phase_counts_full_day_is_hindsight_context": dict(obj.get("source_phase_counts") or {}),
                    "market_sector_context": (obj.get("availability_registry") or {}).get("market_sector_relative_context"),
                    "exchange_mechanics_context": (obj.get("availability_registry") or {}).get("exchange_mechanics_context"),
                },
                "journey_position_and_timing": None if life is None else {"timing": life.get("timing"), "journey_id": life.get("journey_id"), "journey_ordinal": life.get("journey_ordinal")},
                "known_at_status": None if derived is None else (derived.get("causal_timing") or {}).get("known_at_status"),
                "hindsight_resolution_separate": dict(journey.get("hindsight_resolution") or {}),
                "future_resolution_not_used_to_define_formation": True,
            }
        )
    return out


def augment_scientific_object(obj: dict[str, Any]) -> dict[str, Any]:
    attach_semantic_lineage(obj)
    state = build_state_maturity_and_revisit(obj)
    attempts = build_attempt_retest_loop_topology(obj)
    lead_lag = build_lead_lag_graph(obj)
    quality = build_data_quality_audit(obj)
    obj["owner_full_depth_definition_version"] = OWNER_FULL_DEPTH_DEFINITION_VERSION
    obj["state_maturity_persistence_decay"] = state
    obj["attempt_retest_loop_topology"] = attempts
    obj["lead_lag_relationship_graph"] = lead_lag
    obj["data_quality_full_depth_audit"] = quality
    obj["formation_snapshots_owner_full_depth"] = build_enriched_formation_snapshots(obj)
    obj["context_registry"] = {
        "market_sector_cross_sectional": (obj.get("availability_registry") or {}).get("market_sector_relative_context", "UNKNOWN_UNPROVEN"),
        "corporate_action": (obj.get("availability_registry") or {}).get("corporate_action_identity_context", "UNKNOWN_UNPROVEN"),
        "exchange_mechanics": (obj.get("availability_registry") or {}).get("exchange_mechanics_context", "UNKNOWN_UNPROVEN"),
        "source_phase_counts": dict(obj.get("source_phase_counts") or {}),
        "unavailable_context_is_not_fabricated": True,
    }
    obj["near_twin_counterexample_readiness"] = {
        "status": "INPUT_PRESERVED_FOR_CORPUS_LEVEL_STAGE_NOT_YET_NEAR_TWIN_PASS",
        "formation_snapshot_available": bool(obj.get("formation_snapshots_owner_full_depth")),
        "causal_pre_divergence_evidence_required": True,
    }
    obj["base_rate_denominator_readiness"] = {
        "status": "TICKER_DAY_DENOMINATOR_INPUT_PRESERVED_NOT_YET_CORPUS_BASE_RATE_PASS",
        "ticker": obj.get("ticker"),
        "trading_date": obj.get("trading_date"),
        "source_observation_count": obj.get("source_observation_count"),
        "journey_count": len(obj.get("event_journeys", [])),
        "no_forced_event": bool((obj.get("ticker_day_semantic_profile") or {}).get("no_forced_event")),
    }
    obj["owner_full_depth_contract"] = {
        "programmatic_processing_allowed": True,
        "shallow_processing_allowed": False,
        "actual_source_rows_preserved": True,
        "missing_minutes_synthesized": False,
        "causal_hindsight_separation_required": True,
        "formula_stage": "CLOSED",
        "not_full_master_pass": True,
    }
    return obj
