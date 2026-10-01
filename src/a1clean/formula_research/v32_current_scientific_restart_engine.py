from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader, SemanticManifestRow
from . import v32_full_observation_semantic_enrichment as legacy
from .haka_haki_reconstruction import DEC_2024_CONTRACT
from .machine2_current_store import Machine2CurrentStore
from .source_universe_manifest import manifest_digest_is_valid, source_names_from_manifest
from .v32_observation_envelope import packet_to_envelope_bars


LINEAGE = "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V1"
CHECKPOINT_SCHEMA = "A1_M2_CURRENT_SCIENTIFIC_RESTART_CHECKPOINT_V1"
SCIENTIFIC_OBJECT_SCHEMA = "A1_M2_CURRENT_TICKER_DAY_SCIENTIFIC_OBJECT_V1"
DATE_CLOSE_SCHEMA = "A1_M2_CURRENT_DATE_CLOSE_V1"
CHECKPOINT_NAME = f"{LINEAGE}__CHECKPOINT_CURRENT.json"
CURRENT_STATE_NAME = f"{LINEAGE}__STATE_CURRENT.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _delta(value: float | None, previous: float | None) -> float | None:
    return None if value is None or previous is None else value - previous


def _pct(value: float | None, previous: float | None) -> float | None:
    if value is None or previous in (None, 0):
        return None
    return value / previous - 1.0


def _ratio(value: float | None, previous: float | None) -> float | None:
    if value is None or previous in (None, 0):
        return None
    return value / previous


def _sign(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "FLAT"


def _rolling_summary(rows: Sequence[Mapping[str, Any]], end: int, width: int) -> dict[str, Any]:
    if end + 1 < width:
        return {"width_actual_bars": width, "status": "INSUFFICIENT_PRIOR_ACTUAL_BARS"}
    start = end + 1 - width
    window = rows[start : end + 1]
    closes = [_safe_float(row.get("close")) for row in window]
    highs = [_safe_float(row.get("high")) for row in window]
    lows = [_safe_float(row.get("low")) for row in window]
    volumes = [_safe_float(row.get("volume")) for row in window]
    values = [_safe_float(row.get("trade_value")) for row in window]
    nbss = [_safe_float(row.get("nbss")) for row in window]
    valid_highs = [x for x in highs if x is not None]
    valid_lows = [x for x in lows if x is not None]
    valid_volumes = [x for x in volumes if x is not None]
    valid_values = [x for x in values if x is not None]
    valid_nbss = [x for x in nbss if x is not None]
    return {
        "width_actual_bars": width,
        "status": "AVAILABLE",
        "parent_start_source_row": window[0].get("source_row"),
        "parent_end_source_row": window[-1].get("source_row"),
        "parent_start_timestamp": window[0].get("timestamp"),
        "parent_end_timestamp": window[-1].get("timestamp"),
        "close_return": _pct(closes[-1], closes[0]) if closes else None,
        "high": max(valid_highs) if valid_highs else None,
        "low": min(valid_lows) if valid_lows else None,
        "volume_sum": sum(valid_volumes) if valid_volumes else None,
        "trade_value_sum": sum(valid_values) if valid_values else None,
        "nbss_sum": sum(valid_nbss) if valid_nbss else None,
        "known_at_contract": "PARENT_ROWS_ONLY_UP_TO_CURRENT_SOURCE_OBSERVATION",
    }


def build_continuous_current_enrichment(envelope: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Deterministic causal descendants from actual source-supported observations only."""
    rows: list[dict[str, Any]] = []
    prev_close = prev_volume = prev_value = prev_nbss = prev_range = None
    prev_close_delta = prev_volume_delta = prev_value_delta = prev_nbss_delta = None
    running_high = running_low = None
    cumulative_close_path = 0.0
    first_close = None
    fresh_high_attempt = 0
    fresh_low_attempt = 0
    open_cross_attempt = 0
    previous_open_relation = None
    sign_change_counts = Counter()
    timestamp_discontinuities: list[dict[str, Any]] = []

    for i, raw in enumerate(envelope):
        op = _safe_float(raw.get("open")); hi = _safe_float(raw.get("high")); lo = _safe_float(raw.get("low")); close = _safe_float(raw.get("close"))
        volume = _safe_float(raw.get("volume")); value = _safe_float(raw.get("trade_value")); nbss = _safe_float(raw.get("nbss"))
        bar_range = None if hi is None or lo is None else hi - lo
        body = None if op is None or close is None else close - op
        body_abs = None if body is None else abs(body)
        upper_wick = None if hi is None or op is None or close is None else hi - max(op, close)
        lower_wick = None if lo is None or op is None or close is None else min(op, close) - lo
        close_delta = _delta(close, prev_close)
        close_return = _pct(close, prev_close)
        volume_delta = _delta(volume, prev_volume)
        value_delta = _delta(value, prev_value)
        nbss_delta = _delta(nbss, prev_nbss)

        old_high, old_low = running_high, running_low
        if hi is not None:
            running_high = hi if running_high is None else max(running_high, hi)
        if lo is not None:
            running_low = lo if running_low is None else min(running_low, lo)
        fresh_high = hi is not None and (old_high is None or hi > old_high)
        fresh_low = lo is not None and (old_low is None or lo < old_low)
        if fresh_high:
            fresh_high_attempt += 1
        if fresh_low:
            fresh_low_attempt += 1

        if first_close is None and close is not None:
            first_close = close
        if prev_close is not None and close is not None:
            cumulative_close_path += abs(close - prev_close)
        net_displacement = None if first_close is None or close is None else close - first_close
        path_efficiency = None
        if cumulative_close_path > 0 and net_displacement is not None:
            path_efficiency = abs(net_displacement) / cumulative_close_path

        running_span = None if running_high is None or running_low is None else running_high - running_low
        running_location = None
        if close is not None and running_span not in (None, 0):
            running_location = (close - running_low) / running_span

        open_relation = "UNKNOWN"
        if op is not None and close is not None:
            open_relation = "ABOVE_OPEN" if close > op else "BELOW_OPEN" if close < op else "AT_OPEN"
        if previous_open_relation is not None and open_relation != "UNKNOWN" and previous_open_relation != open_relation:
            open_cross_attempt += 1
        if open_relation != "UNKNOWN":
            previous_open_relation = open_relation

        response_efficiency_nbss = None
        if close_delta is not None and nbss not in (None, 0):
            response_efficiency_nbss = abs(close_delta) / abs(nbss)
        response_efficiency_volume = None
        if close_delta is not None and volume not in (None, 0):
            response_efficiency_volume = abs(close_delta) / abs(volume)

        lead_lag_change = {
            "price": _sign(close_delta),
            "volume": _sign(volume_delta),
            "value": _sign(value_delta),
            "nbss": _sign(nbss_delta),
            "range": _sign(_delta(bar_range, prev_range)),
        }
        for lane, state in lead_lag_change.items():
            if state not in {"UNKNOWN", "FLAT"}:
                sign_change_counts[lane] += 1

        negative_evidence: list[str] = []
        if nbss not in (None, 0) and close_delta == 0:
            negative_evidence.append("FLOW_PRESENT_PRICE_NO_RESPONSE_THIS_OBSERVATION")
        if volume_delta is not None and volume_delta > 0 and close_delta == 0:
            negative_evidence.append("ACTIVITY_INCREASE_PRICE_NO_RESPONSE_THIS_OBSERVATION")
        if fresh_high and close is not None and hi is not None and close < hi:
            negative_evidence.append("FRESH_HIGH_NOT_FULLY_RETAINED_AT_CLOSE")
        if fresh_low and close is not None and lo is not None and close > lo:
            negative_evidence.append("FRESH_LOW_NOT_FULLY_RETAINED_AT_CLOSE")

        quality = {
            "duplicate_timestamp": False,
            "out_of_order_timestamp": False,
            "source_field_count": raw.get("source_field_count"),
            "source_packet_fingerprint": raw.get("source_packet_fingerprint"),
            "stale_state": "UNKNOWN_UNPROVEN",
            "correction_state": "UNKNOWN_UNPROVEN",
            "reconnect_state": "UNKNOWN_UNPROVEN",
        }
        if i > 0:
            try:
                p = datetime.fromisoformat(str(envelope[i - 1].get("timestamp")))
                c = datetime.fromisoformat(str(raw.get("timestamp")))
                delta_seconds = (c - p).total_seconds()
            except ValueError:
                delta_seconds = None
            if delta_seconds is not None and delta_seconds != 60.0:
                rec = {
                    "previous_timestamp": envelope[i - 1].get("timestamp"),
                    "timestamp": raw.get("timestamp"),
                    "delta_seconds": delta_seconds,
                    "interpretation": "SESSION_RECESS_OR_SOURCE_GAP_NOT_INFERRED",
                }
                timestamp_discontinuities.append(rec)
                quality["timestamp_discontinuity"] = rec

        derived = {
            "index": i,
            "source_row": raw.get("source_row"),
            "timestamp": raw.get("timestamp"),
            "source_phase": raw.get("source_phase"),
            "regular_behavior_eligible": raw.get("regular_behavior_eligible"),
            "price_geometry": {
                "open": op, "high": hi, "low": lo, "close": close,
                "range": bar_range, "body": body, "body_abs": body_abs,
                "upper_wick": upper_wick, "lower_wick": lower_wick,
                "close_delta": close_delta, "close_return": close_return,
                "net_displacement_from_first_close": net_displacement,
                "cumulative_close_path_length": cumulative_close_path,
                "path_efficiency": path_efficiency,
                "running_high": running_high, "running_low": running_low,
                "running_location_0_1": running_location,
                "distance_from_running_high": None if close is None or running_high is None else running_high - close,
                "distance_from_running_low": None if close is None or running_low is None else close - running_low,
                "fresh_high": fresh_high, "fresh_low": fresh_low,
                "fresh_high_attempt_number": fresh_high_attempt if fresh_high else None,
                "fresh_low_attempt_number": fresh_low_attempt if fresh_low else None,
                "open_relation": open_relation,
                "open_cross_attempt_count_to_now": open_cross_attempt,
                "range_ratio_to_previous": _ratio(bar_range, prev_range),
                "range_delta": _delta(bar_range, prev_range),
            },
            "activity_flow": {
                "volume": volume, "volume_delta": volume_delta,
                "volume_acceleration": _delta(volume_delta, prev_volume_delta),
                "trade_value": value, "trade_value_delta": value_delta,
                "trade_value_acceleration": _delta(value_delta, prev_value_delta),
                "nbss": nbss, "nbss_delta": nbss_delta,
                "nbss_acceleration": _delta(nbss_delta, prev_nbss_delta),
                "haka": raw.get("haka"), "haki": raw.get("haki"),
                "haka_haki_status": raw.get("haka_haki_status"),
            },
            "effort_response": {
                "nbss_to_price_absolute_efficiency": response_efficiency_nbss,
                "volume_to_price_absolute_efficiency": response_efficiency_volume,
                "price_response_direction": _sign(close_delta),
                "negative_evidence": negative_evidence,
            },
            "lead_lag_observation": lead_lag_change,
            "multi_timescale_descendants": {
                "3_actual_bars": _rolling_summary(envelope, i, 3),
                "5_actual_bars": _rolling_summary(envelope, i, 5),
                "15_actual_bars": _rolling_summary(envelope, i, 15),
            },
            "causal_timing": {
                "event_time": raw.get("timestamp"),
                "source_time": raw.get("timestamp"),
                "known_at": None,
                "formation_eligible_at": None,
                "known_at_status": "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS",
                "hindsight_fields_present": False,
            },
            "data_quality": quality,
        }
        rows.append(derived)

        prev_close, prev_volume, prev_value, prev_nbss, prev_range = close, volume, value, nbss, bar_range
        prev_close_delta, prev_volume_delta, prev_value_delta, prev_nbss_delta = close_delta, volume_delta, value_delta, nbss_delta

    return {
        "derived_observation_count": len(rows),
        "derived_observations": rows,
        "attempt_topology": {
            "fresh_high_attempts": fresh_high_attempt,
            "fresh_low_attempts": fresh_low_attempt,
            "open_relation_cross_attempts": open_cross_attempt,
        },
        "lead_lag_activity_counts": dict(sorted(sign_change_counts.items())),
        "timestamp_discontinuities": timestamp_discontinuities,
        "timestamp_discontinuity_count": len(timestamp_discontinuities),
    }


def _formation_snapshots(journeys: Sequence[Mapping[str, Any]], regular: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ordinal, journey in enumerate(journeys):
        start = dict(journey.get("causal_start") or {})
        idx = start.get("index")
        bar = regular[int(idx)] if isinstance(idx, int) and 0 <= idx < len(regular) else None
        out.append(
            {
                "journey_ordinal": ordinal,
                "journey_kind": journey.get("journey_kind"),
                "causal_start": start,
                "formation_snapshot": {
                    "source_row": None if bar is None else bar.get("source_row"),
                    "timestamp": None if bar is None else bar.get("timestamp"),
                    "source_phase": None if bar is None else bar.get("source_phase"),
                    "open": None if bar is None else bar.get("open"),
                    "high": None if bar is None else bar.get("high"),
                    "low": None if bar is None else bar.get("low"),
                    "close": None if bar is None else bar.get("close"),
                    "volume": None if bar is None else bar.get("volume"),
                    "trade_value": None if bar is None else bar.get("trade_value"),
                    "nbss": None if bar is None else bar.get("nbss"),
                    "haka": None if bar is None else bar.get("haka"),
                    "haki": None if bar is None else bar.get("haki"),
                    "known_at_status": "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS",
                },
                "hindsight_resolution_separate": dict(journey.get("hindsight_resolution") or {}),
                "future_resolution_not_used_to_define_start": bool(journey.get("future_resolution_not_used_to_define_start")),
            }
        )
    return out


def build_current_scientific_object(
    *,
    packet,
    source_identity: Mapping[str, Any],
    carry_in: Mapping[str, Any] | None,
    previous_governed_date: str | None,
) -> dict[str, Any]:
    source = str(source_identity["source_name"])
    ticker = str(packet.identity.ticker)
    day = str(packet.identity.trading_date)
    allow_haka_haki = source == str(DEC_2024_CONTRACT["source_name"])
    envelope = packet_to_envelope_bars(packet, allow_haka_haki=allow_haka_haki)
    regular = [row for row in envelope if row.get("regular_behavior_eligible")]
    nonregular = [row for row in envelope if not row.get("regular_behavior_eligible")]

    td, runs, journeys = legacy.enrich_ticker_day(
        regular,
        source=source,
        source_identity=source_identity,
        ticker=ticker,
        trading_date=day,
        carry_in=carry_in,
        previous_governed_date=previous_governed_date,
        allow_haka_haki=allow_haka_haki,
    )
    td = legacy._rewrite_v32(td)
    runs = [legacy._rewrite_v32(dict(row)) for row in runs]
    journeys = [legacy._rewrite_v32(dict(row)) for row in journeys]
    behavior_day, lifecycle_records, behavior_path = legacy.enrich_behavior_lifecycle(
        bars=regular,
        full_envelope=envelope,
        runs=runs,
        journeys=journeys,
        source=source,
        ticker=ticker,
        trading_date=day,
        carry_in=carry_in,
    )
    if len(lifecycle_records) != len(journeys):
        raise RuntimeError(f"M2_CURRENT_LIFECYCLE_COVERAGE_FAIL:{source}:{day}:{ticker}")

    continuous = build_continuous_current_enrichment(envelope)
    source_ref = {
        "source_name": source,
        "source_drive_id": source_identity.get("source_drive_id"),
        "source_sha256": source_identity.get("source_sha256"),
        "generation_id": source_identity.get("generation_id"),
        "semantic_manifest_fingerprint": source_identity.get("semantic_manifest_fingerprint"),
        "packet_fingerprint": packet.packet_fingerprint,
        "source_header": list(packet.header),
        "source_header_field_count": len(packet.header),
        "source_row_first": packet.identity.source_row_first,
        "source_row_last": packet.identity.source_row_last,
        "source_row_count": packet.row_count,
        "first_timestamp": packet.timestamps[0].isoformat(sep=" "),
        "last_timestamp": packet.timestamps[-1].isoformat(sep=" "),
        "full_source_values_retrievable_from_canonical_packet": True,
        "raw_payload_duplicated_in_scientific_output": False,
    }
    availability = {
        "participant_broker_flow": "UNKNOWN_UNPROVEN",
        "tick_time_and_trade_aggressor": "FUTURE_LANE_NOT_ADMITTED",
        "l1_bbo": "FUTURE_LANE_NOT_ADMITTED",
        "l2_depth_orderbook_queue": "FUTURE_LANE_NOT_ADMITTED",
        "foreign_domestic_detail": "UNKNOWN_UNPROVEN",
        "market_sector_relative_context": "UNKNOWN_UNPROVEN",
        "corporate_action_identity_context": "UNKNOWN_UNPROVEN",
        "exchange_mechanics_context": "PARTIAL_SOURCE_PHASE_AVAILABLE_OTHER_MECHANICS_UNPROVEN",
        "haka_haki": "SOURCE_BOUND_PROVEN" if allow_haka_haki else "SEMANTICS_UNPROVEN_FOR_SOURCE",
    }
    blindspots = [
        "KNOWN_AT_BAR_COMPLETION_SEMANTICS_UNPROVEN",
        "MARKET_SECTOR_RELATIVE_CONTEXT_NOT_YET_CAUSALLY_BOUND",
        "CORPORATE_ACTION_IDENTITY_CONTEXT_NOT_YET_CAUSALLY_BOUND",
        "PARTICIPANT_TICK_L1_L2_QUEUE_LANES_NOT_ADMITTED",
        "CROSS_TICKER_CROSS_DATE_CROSS_MONTH_RECURRENCE_REQUIRES_LATER_RECONCILIATION",
        "NEAR_TWIN_AND_BASE_RATE_REQUIRE_CORPUS_LEVEL_STAGE",
    ]
    result = {
        "schema": SCIENTIFIC_OBJECT_SCHEMA,
        "lineage": LINEAGE,
        "status": "CURRENT_RESTART_UNIT_COMPLETE_NOT_FINAL_PASS",
        "source_ref": source_ref,
        "ticker": ticker,
        "trading_date": day,
        "source_observation_count": len(envelope),
        "regular_behavior_observation_count": len(regular),
        "nonregular_context_observation_count": len(nonregular),
        "source_phase_counts": dict(sorted(Counter(str(x.get("source_phase")) for x in envelope).items())),
        "continuous_current_enrichment": continuous,
        "ticker_day_semantic_profile": td,
        "state_runs": runs,
        "event_journeys": journeys,
        "behavior_day": behavior_day,
        "behavior_lifecycle": lifecycle_records,
        "behavior_path": behavior_path,
        "formation_snapshots": _formation_snapshots(journeys, regular),
        "availability_registry": availability,
        "negative_quiet_failure_preserved": True,
        "unnamed_transitions_preserved": True,
        "open_censored_preserved": True,
        "causal_formation_and_hindsight_physically_separated_in_object": True,
        "future_lanes_not_fabricated": True,
        "blindspot_register_additions": blindspots,
        "terminal_carry_state": td.get("terminal_carry_state"),
        "previous_governed_date": previous_governed_date,
        "created_at_utc": _utc_now(),
    }
    result["scientific_object_sha256"] = _sha256_bytes(_canon(result))
    return result


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"M2_CURRENT_JSON_NOT_OBJECT:{path}")
    return obj


def _resolve_source_record(manifest: Mapping[str, Any], trading_date: str) -> Mapping[str, Any]:
    matches = [
        row for row in manifest.get("sources", [])
        if str(row.get("first_date") or "") <= trading_date <= str(row.get("last_date") or "")
    ]
    if len(matches) != 1:
        raise RuntimeError(f"M2_CURRENT_DATE_SOURCE_CARDINALITY:{trading_date}:{len(matches)}")
    return matches[0]


def _actual_first_date(reader: GovernedSourceReader) -> str:
    if not reader.semantic_manifest_rows:
        raise RuntimeError("M2_CURRENT_EMPTY_SEMANTIC_MANIFEST")
    return str(reader.semantic_manifest_rows[0].trading_date)


def _ref(row: SemanticManifestRow, position: int) -> dict[str, Any]:
    return {
        "selection_position": position,
        **row.as_dict(),
    }


def _validate_source_identity(reader: GovernedSourceReader, record: Mapping[str, Any]) -> None:
    identity = reader.identity.as_dict()
    if str(identity.get("source_drive_id")) != str(record.get("source_drive_id")):
        raise RuntimeError("M2_CURRENT_SOURCE_ID_DRIFT")
    if str(identity.get("source_sha256")) != str(record.get("digest_sha256")):
        raise RuntimeError("M2_CURRENT_SOURCE_DIGEST_DRIFT")


def _checkpoint_identity(
    *,
    request: Mapping[str, Any],
    request_sha256: str,
    manifest: Mapping[str, Any],
    software_revision: str,
) -> dict[str, Any]:
    authority_sync = dict(manifest.get("authority_sync") or {})
    return {
        "lineage": LINEAGE,
        "request_sha256": request_sha256,
        "software_revision": software_revision,
        "source_universe_manifest_digest": manifest.get("manifest_digest"),
        "authority_corpus_sha256": authority_sync.get("authority_corpus_sha256"),
        "master_document_id": request.get("master_handbook_document_id"),
        "master_revision_id": request.get("master_handbook_revision_id"),
        "coverage_matrix_document_id": request.get("machine2_master_coverage_matrix_document_id"),
        "coverage_matrix_revision_id": request.get("machine2_master_coverage_matrix_revision_id"),
        "old_pass_completion_inherited": False,
        "old_scientific_checkpoint_read_for_completion": False,
    }


def run_trading_date(
    *,
    request_path: Path,
    source_universe_manifest_path: Path,
    trading_date: str,
    software_revision: str,
    units_per_shard: int = 20,
) -> dict[str, Any]:
    if units_per_shard <= 0:
        raise RuntimeError("M2_CURRENT_UNITS_PER_SHARD_MUST_BE_POSITIVE")
    if not software_revision or software_revision == "LOCAL_UNVERSIONED":
        raise RuntimeError("M2_CURRENT_SOFTWARE_REVISION_REQUIRED")
    request = _load_json(request_path)
    if request.get("enabled") is not True or request.get("restart_authorized") is not True:
        raise RuntimeError("M2_CURRENT_HEAVY_RESTART_NOT_AUTHORIZED")
    if request.get("machine2_full_scientific_restart_from_beginning_required") is not True:
        raise RuntimeError("M2_CURRENT_RESTART_CONTRACT_MISSING")
    if request.get("old_pass_may_skip_current_reading_unit") is not False:
        raise RuntimeError("M2_CURRENT_OLD_PASS_SKIP_NOT_FORBIDDEN")
    if request.get("old_derived_semantic_checkpoint_completion_inherited") is not False:
        raise RuntimeError("M2_CURRENT_OLD_CHECKPOINT_INHERITANCE_NOT_FORBIDDEN")

    manifest = _load_json(source_universe_manifest_path)
    if not manifest_digest_is_valid(manifest) or manifest.get("status") != "PASS":
        raise RuntimeError("M2_CURRENT_SOURCE_UNIVERSE_NOT_PASS")
    source_names_from_manifest(manifest, require_pass=True)
    request_sha256 = _sha256_file(request_path)
    identity_contract = _checkpoint_identity(
        request=request,
        request_sha256=request_sha256,
        manifest=manifest,
        software_revision=software_revision,
    )

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    store = Machine2CurrentStore(writer_api)

    source_record = _resolve_source_record(manifest, trading_date)
    source_name = str(source_record["source_name"])
    reader = GovernedSourceReader(reader_api, source_name=source_name)
    _validate_source_identity(reader, source_record)
    selected = [row for row in reader.semantic_manifest_rows if row.trading_date == trading_date]
    if not selected:
        raise RuntimeError(f"M2_CURRENT_DATE_EMPTY:{trading_date}")

    checkpoint = store.read_json_optional(store.checkpoint_folder_id, CHECKPOINT_NAME)
    if checkpoint is None:
        first_source_name = str(manifest["sources"][0]["source_name"])
        first_reader = reader if first_source_name == source_name else GovernedSourceReader(reader_api, source_name=first_source_name)
        first_date = _actual_first_date(first_reader)
        if trading_date != first_date or source_name != first_source_name:
            raise RuntimeError(f"M2_CURRENT_MUST_START_AT_FIRST_GOVERNED_DATE:{first_source_name}:{first_date}")
        checkpoint = {
            "schema": CHECKPOINT_SCHEMA,
            **identity_contract,
            "status": "IN_PROGRESS",
            "created_at_utc": _utc_now(),
            "updated_at_utc": _utc_now(),
            "current_source": source_name,
            "current_date": trading_date,
            "last_closed_date": None,
            "completed_units_in_current_date": 0,
            "completed_source_rows_in_current_date": 0,
            "output_shards": [],
            "last_completed": None,
            "next_exact_resume_point": _ref(selected[0], 0),
            "carry_by_ticker": {},
            "hold": None,
        }
        store.upsert_json(folder_id=store.checkpoint_folder_id, name=CHECKPOINT_NAME, obj=checkpoint)
    else:
        if checkpoint.get("schema") != CHECKPOINT_SCHEMA:
            raise RuntimeError("M2_CURRENT_CHECKPOINT_SCHEMA_MISMATCH")
        actual_identity = {key: checkpoint.get(key) for key in identity_contract}
        if actual_identity != identity_contract:
            raise RuntimeError("M2_CURRENT_CHECKPOINT_CURRENT_CONTRACT_IDENTITY_MISMATCH")
        if checkpoint.get("status") == "DATE_CLOSED" and checkpoint.get("current_date") == trading_date:
            return {
                "status": "NOOP_DATE_ALREADY_CLOSED_IN_NEW_CURRENT_LINEAGE",
                "lineage": LINEAGE,
                "trading_date": trading_date,
                "next_exact_resume_point": None,
            }
        if checkpoint.get("current_date") != trading_date or checkpoint.get("current_source") != source_name:
            raise RuntimeError("M2_CURRENT_NO_AUTO_ADVANCE_DATE_OR_SOURCE")

    start = int(checkpoint.get("completed_units_in_current_date") or 0)
    if start < 0 or start > len(selected):
        raise RuntimeError("M2_CURRENT_CHECKPOINT_UNIT_CURSOR_INVALID")
    shard_ordinal = len(checkpoint.get("output_shards") or []) + 1
    carry_by_ticker = dict(checkpoint.get("carry_by_ticker") or {})

    while start < len(selected):
        end = min(start + units_per_shard, len(selected))
        buffer = io.StringIO()
        shard_rows = 0
        pending_carry = dict(carry_by_ticker)
        for pos in range(start, end):
            manifest_row = selected[pos]
            packet = reader.load_packet(manifest_row.manifest_index)
            prior = pending_carry.get(packet.identity.ticker)
            prior_date = None if prior is None else prior.get("date")
            obj = build_current_scientific_object(
                packet=packet,
                source_identity=reader.identity.as_dict(),
                carry_in=prior,
                previous_governed_date=prior_date,
            )
            buffer.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            buffer.write("\n")
            shard_rows += packet.row_count
            pending_carry[str(packet.identity.ticker)] = {
                "date": str(packet.identity.trading_date),
                "source": source_name,
                "terminal_carry_state": obj.get("terminal_carry_state"),
                "open_journey_kinds": sorted(
                    str(j.get("journey_kind"))
                    for j in obj.get("event_journeys", [])
                    if bool((j.get("hindsight_resolution") or {}).get("right_censored"))
                ),
                "scientific_object_sha256": obj.get("scientific_object_sha256"),
            }

        shard_name = f"{LINEAGE}__{trading_date}__SHARD_{shard_ordinal:05d}.jsonl"
        uploaded = store.upsert_bytes(
            folder_id=store.output_folder_id,
            name=shard_name,
            data=buffer.getvalue().encode("utf-8"),
            mime_type="application/x-ndjson",
        )
        checkpoint.setdefault("output_shards", []).append(
            {
                **uploaded,
                "shard_ordinal": shard_ordinal,
                "selection_position_first": start,
                "selection_position_last": end - 1,
                "packet_count": end - start,
                "source_row_count": shard_rows,
                "first_unit": _ref(selected[start], start),
                "last_unit": _ref(selected[end - 1], end - 1),
            }
        )
        checkpoint["completed_units_in_current_date"] = end
        checkpoint["completed_source_rows_in_current_date"] = int(checkpoint.get("completed_source_rows_in_current_date") or 0) + shard_rows
        checkpoint["last_completed"] = _ref(selected[end - 1], end - 1)
        checkpoint["next_exact_resume_point"] = None if end == len(selected) else _ref(selected[end], end)
        checkpoint["carry_by_ticker"] = pending_carry
        checkpoint["updated_at_utc"] = _utc_now()
        checkpoint["status"] = "RECONCILING_DATE" if end == len(selected) else "IN_PROGRESS"
        checkpoint["hold"] = None
        store.upsert_json(folder_id=store.checkpoint_folder_id, name=CHECKPOINT_NAME, obj=checkpoint)
        carry_by_ticker = pending_carry
        start = end
        shard_ordinal += 1

    expected_rows = sum(row.data_row_count for row in selected)
    if int(checkpoint["completed_units_in_current_date"]) != len(selected):
        raise RuntimeError("M2_CURRENT_DATE_PACKET_RECONCILIATION_FAIL")
    if int(checkpoint["completed_source_rows_in_current_date"]) != expected_rows:
        raise RuntimeError("M2_CURRENT_DATE_SOURCE_ROW_RECONCILIATION_FAIL")

    date_close = {
        "schema": DATE_CLOSE_SCHEMA,
        "lineage": LINEAGE,
        **identity_contract,
        "status": "DATE_CLOSE_CURRENT_RESTART_PASS",
        "source": source_name,
        "source_drive_id": reader.identity.source_drive_id,
        "source_sha256": reader.identity.source_sha256,
        "trading_date": trading_date,
        "ticker_day_count": len(selected),
        "source_row_count": expected_rows,
        "first_unit": _ref(selected[0], 0),
        "last_unit": _ref(selected[-1], len(selected) - 1),
        "output_shards": checkpoint["output_shards"],
        "negative_quiet_failure_not_filtered": True,
        "old_pass_completion_inherited": False,
        "old_scientific_checkpoint_read_for_completion": False,
        "formula_stage": "CLOSED",
        "grouping_stage": "HOLD",
        "next_date_auto_opened": False,
        "closed_at_utc": _utc_now(),
    }
    close_name = f"{LINEAGE}__DATE_CLOSE__{trading_date}.json"
    close_upload = store.upsert_json(folder_id=store.current_state_folder_id, name=close_name, obj=date_close)
    checkpoint["status"] = "DATE_CLOSED"
    checkpoint["last_closed_date"] = trading_date
    checkpoint["date_close"] = close_upload
    checkpoint["next_exact_resume_point"] = None
    checkpoint["updated_at_utc"] = _utc_now()
    store.upsert_json(folder_id=store.checkpoint_folder_id, name=CHECKPOINT_NAME, obj=checkpoint)
    state = {
        "schema": "A1_M2_CURRENT_SCIENTIFIC_RESTART_STATE_V1",
        "lineage": LINEAGE,
        "status": "DATE_CLOSED_WAITING_EXPLICIT_NEXT_DATE_AUTHORITY",
        "last_closed_date": trading_date,
        "current_source": source_name,
        "date_close": close_upload,
        "checkpoint_name": CHECKPOINT_NAME,
        "old_pass_completion_inherited": False,
        "formula_stage": "CLOSED",
        "grouping_stage": "HOLD",
        "updated_at_utc": _utc_now(),
    }
    store.upsert_json(folder_id=store.current_state_folder_id, name=CURRENT_STATE_NAME, obj=state)
    return date_close


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Machine-2 CURRENT scientific restart from the earliest governed unit; one trading date only, no auto-advance.")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--source-universe-manifest", required=True, type=Path)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--units-per-shard", type=int, default=20)
    parser.add_argument("--software-revision", default=os.environ.get("GITHUB_SHA", "LOCAL_UNVERSIONED"))
    args = parser.parse_args(argv)
    result = run_trading_date(
        request_path=args.request,
        source_universe_manifest_path=args.source_universe_manifest,
        trading_date=args.trading_date,
        software_revision=args.software_revision,
        units_per_shard=args.units_per_shard,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
