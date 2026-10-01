from __future__ import annotations

from typing import Any, Mapping

from .m2_full_depth_extension import augment_scientific_object as _augment_v1


DEFINITION_VERSION = "A1_M2_OWNER_FULL_DEPTH_20261001_V2"


def _rows(obj: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(x) for x in (obj.get("continuous_current_enrichment") or {}).get("derived_observations", [])]


def _row_by_timestamp(obj: Mapping[str, Any], timestamp: Any) -> tuple[int | None, dict[str, Any] | None]:
    target = str(timestamp or "")
    if not target:
        return None, None
    for i, row in enumerate(_rows(obj)):
        if str(row.get("timestamp") or "") == target:
            return i, row
    return None, None


def _source_parent(obj: Mapping[str, Any], start_ts: Any, end_ts: Any) -> dict[str, Any]:
    source = dict(obj.get("source_ref") or {})
    _, start = _row_by_timestamp(obj, start_ts)
    _, end = _row_by_timestamp(obj, end_ts)
    return {
        "source_name": source.get("source_name"),
        "source_drive_id": source.get("source_drive_id"),
        "source_sha256": source.get("source_sha256"),
        "generation_id": source.get("generation_id"),
        "packet_fingerprint": source.get("packet_fingerprint"),
        "source_row_first": None if start is None else start.get("source_row"),
        "source_row_last": None if end is None else end.get("source_row"),
        "timestamp_first": None if start is None else start.get("timestamp"),
        "timestamp_last": None if end is None else end.get("timestamp"),
        "resolved_by": "EXACT_TIMESTAMP_IN_FULL_ENVELOPE",
    }


def _fix_lineage(obj: dict[str, Any]) -> None:
    runs = [dict(x) for x in obj.get("state_runs", [])]
    for run in runs:
        run["definition_version"] = DEFINITION_VERSION
        run["source_parents"] = _source_parent(obj, run.get("start_timestamp"), run.get("end_timestamp"))
    obj["state_runs"] = runs

    journeys = [dict(x) for x in obj.get("event_journeys", [])]
    for journey in journeys:
        start = dict(journey.get("causal_start") or {})
        resolution = dict(journey.get("hindsight_resolution") or {})
        start_ts = start.get("timestamp")
        end_ts = resolution.get("resolution_timestamp") or start_ts
        journey["definition_version"] = DEFINITION_VERSION
        journey["source_parents"] = _source_parent(obj, start_ts, end_ts)
    obj["event_journeys"] = journeys


def _rebuild_formation_snapshots(obj: Mapping[str, Any]) -> list[dict[str, Any]]:
    runs = [dict(x) for x in obj.get("state_runs", [])]
    journeys = [dict(x) for x in obj.get("event_journeys", [])]
    lifecycle = [dict(x) for x in obj.get("behavior_lifecycle", [])]
    out: list[dict[str, Any]] = []
    for i, journey in enumerate(journeys):
        start = dict(journey.get("causal_start") or {})
        start_ts = start.get("timestamp")
        full_index, derived = _row_by_timestamp(obj, start_ts)
        covering = next(
            (
                run for run in runs
                if str(run.get("start_timestamp") or "") <= str(start_ts or "") <= str(run.get("end_timestamp") or "")
            ),
            None,
        )
        life = lifecycle[i] if i < len(lifecycle) else None
        out.append(
            {
                "definition_version": DEFINITION_VERSION,
                "journey_ordinal": i + 1,
                "journey_kind": journey.get("journey_kind"),
                "causal_timestamp": start_ts,
                "full_envelope_index": full_index,
                "source_identity": dict(obj.get("source_ref") or {}),
                "available_actual_source_rows_through_formation": None if full_index is None else full_index + 1,
                "primitive_and_continuous_derived_at_formation": derived,
                "state_run_at_formation": covering,
                "availability_at_formation": dict(obj.get("availability_registry") or {}),
                "journey_position_and_timing": None if life is None else {
                    "journey_id": life.get("journey_id"),
                    "journey_ordinal": life.get("journey_ordinal"),
                    "timing": life.get("timing"),
                },
                "known_at_status": None if derived is None else (derived.get("causal_timing") or {}).get("known_at_status"),
                "hindsight_resolution_separate": dict(journey.get("hindsight_resolution") or {}),
                "future_resolution_not_used_to_define_formation": True,
            }
        )
    return out


def augment_scientific_object(obj: dict[str, Any]) -> dict[str, Any]:
    out = _augment_v1(obj)
    _fix_lineage(out)
    out["owner_full_depth_definition_version"] = DEFINITION_VERSION
    out["owner_full_depth_index_alignment"] = "EXACT_TIMESTAMP_FULL_ENVELOPE_NOT_REGULAR_INDEX_ASSUMPTION"
    out["formation_snapshots_owner_full_depth"] = _rebuild_formation_snapshots(out)
    return out
