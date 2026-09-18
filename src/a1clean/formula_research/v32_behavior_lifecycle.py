from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime
from typing import Any, Mapping, Sequence

from .minute_behavior_census_v21 import _flow_price_relation, _pct, _sign
from .v30_semantic_journey_enrichment import _safe_float

SCHEMA = "A1_V32_BEHAVIOR_LIFECYCLE_V1"

LIFECYCLE_TIMING_FIELDS = (
    "precursor_start_time",
    "first_observed_time",
    "event_start_time",
    "first_detectable_time",
    "change_point_time",
    "known_at_time",
    "confirm_time",
    "peak_time",
    "trough_time",
    "extreme_time",
    "weakening_time",
    "fail_time",
    "recovery_time",
    "rebase_or_transformation_time",
    "invalidation_time",
    "event_end_time",
    "last_observed_time",
    "follow_through_end_time",
)


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def _snapshot(bar: Mapping[str, Any] | None, index: int | None = None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        "index": index,
        "timestamp": bar.get("timestamp"),
        "source_row": bar.get("source_row"),
        "source_phase": bar.get("source_phase"),
        "observation_role": bar.get("observation_role"),
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "trade_value": bar.get("trade_value"),
        "nbss": bar.get("nbss"),
        "flow_available": bar.get("flow_available"),
        "mechanism_eligible": bar.get("mechanism_eligible"),
        "session_eligible": bar.get("session_eligible"),
        "regular_behavior_eligible": bar.get("regular_behavior_eligible"),
        "haka": bar.get("haka"),
        "haki": bar.get("haki"),
        "haka_haki_status": bar.get("haka_haki_status"),
    }


def _timestamp(bar: Mapping[str, Any] | None) -> str | None:
    if not bar:
        return None
    value = str(bar.get("timestamp") or "")
    return value or None


def _price_direction(bars: Sequence[Mapping[str, Any]], i: int) -> str:
    if i <= 0:
        return "UNKNOWN"
    cur = _safe_float(bars[i].get("close"))
    prev = _safe_float(bars[i - 1].get("close"))
    return _sign(_pct(cur, prev) if prev not in (None, 0.0) else None)


def _flow_relation(bars: Sequence[Mapping[str, Any]], i: int) -> str:
    if i <= 0:
        return "NO_PROVEN_FLOW"
    cur = bars[i]
    flow_ok = bool(cur.get("flow_available", False)) and bool(cur.get("mechanism_eligible", False))
    nbss = _safe_float(cur.get("nbss")) if flow_ok else None
    close = _safe_float(cur.get("close"))
    prev_close = _safe_float(bars[i - 1].get("close"))
    delta = _pct(close, prev_close) if prev_close not in (None, 0.0) else None
    return _flow_price_relation(nbss, delta, flow_ok)


def _index_for_timestamp(bars: Sequence[Mapping[str, Any]], ts: str | None) -> int | None:
    if not ts:
        return None
    for i, bar in enumerate(bars):
        if str(bar.get("timestamp") or "") == ts:
            return i
    return None


def _journey_bounds(
    bars: Sequence[Mapping[str, Any]],
    journey: Mapping[str, Any],
) -> tuple[int, int, bool, str | None]:
    start = dict(journey.get("causal_start") or {})
    start_index = start.get("index")
    if not isinstance(start_index, int):
        start_index = _index_for_timestamp(bars, str(start.get("timestamp") or "") or None)
    if start_index is None:
        raise RuntimeError(f"V32_LIFECYCLE_START_INDEX_UNRESOLVED:{journey.get('journey_kind')}")
    if start_index < 0 or start_index >= len(bars):
        raise RuntimeError(f"V32_LIFECYCLE_START_INDEX_OUT_OF_RANGE:{start_index}:{len(bars)}")

    resolution = dict(journey.get("hindsight_resolution") or {})
    right_censored = bool(resolution.get("right_censored"))
    resolution_ts = str(resolution.get("resolution_timestamp") or "") or None
    end_index = resolution.get("resolution_index")
    if not isinstance(end_index, int):
        end_index = _index_for_timestamp(bars, resolution_ts)
    if end_index is None:
        end_index = len(bars) - 1
    if end_index < start_index:
        raise RuntimeError(f"V32_LIFECYCLE_END_BEFORE_START:{start_index}:{end_index}")
    end_index = min(end_index, len(bars) - 1)
    return start_index, end_index, right_censored, resolution_ts


def _event_predicate(
    kind: str,
    bars: Sequence[Mapping[str, Any]],
    i: int,
    *,
    session_open: float | None,
) -> bool:
    if kind == "RECOVERY":
        return _price_direction(bars, i) == "UP"
    if kind == "PULLBACK":
        return _price_direction(bars, i) == "DOWN"
    if kind == "OPEN_BREAK_RECLAIM":
        lo = _safe_float(bars[i].get("low"))
        close = _safe_float(bars[i].get("close"))
        if session_open is None:
            return False
        return (lo is not None and lo < session_open) or (close is not None and close < session_open)
    if kind == "BUY_NONRESPONSE_WINDOW":
        return _flow_relation(bars, i) == "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE"
    if kind == "SELL_RESILIENCE_WINDOW":
        return _flow_relation(bars, i) == "SELL_FLOW_PRICE_RESILIENCE"
    return False


def _direction(kind: str) -> str:
    if kind == "RECOVERY":
        return "UP"
    if kind in {"PULLBACK", "OPEN_BREAK_RECLAIM"}:
        return "DOWN"
    return "NON_DIRECTIONAL_RELATION"


def _first_confirmation(
    kind: str,
    bars: Sequence[Mapping[str, Any]],
    start: int,
    end: int,
    *,
    session_open: float | None,
) -> int | None:
    for i in range(start + 1, end + 1):
        if _event_predicate(kind, bars, i, session_open=session_open):
            return i
    return None


def _extreme_indices(
    bars: Sequence[Mapping[str, Any]],
    start: int,
    end: int,
) -> tuple[int | None, int | None, int | None, int | None]:
    peak_first = peak_last = trough_first = trough_last = None
    peak = trough = None
    for i in range(start, end + 1):
        hi = _safe_float(bars[i].get("high"))
        lo = _safe_float(bars[i].get("low"))
        if hi is not None:
            if peak is None or hi > peak:
                peak = hi
                peak_first = peak_last = i
            elif hi == peak:
                peak_last = i
        if lo is not None:
            if trough is None or lo < trough:
                trough = lo
                trough_first = trough_last = i
            elif lo == trough:
                trough_last = i
    return peak_first, peak_last, trough_first, trough_last


def _first_counter_move(
    bars: Sequence[Mapping[str, Any]],
    *,
    start: int,
    end: int,
    direction: str,
) -> int | None:
    for i in range(max(start + 1, 1), end + 1):
        d = _price_direction(bars, i)
        if direction == "UP" and d == "DOWN":
            return i
        if direction == "DOWN" and d == "UP":
            return i
    return None


def _first_resumption(
    bars: Sequence[Mapping[str, Any]],
    *,
    start: int | None,
    end: int,
    direction: str,
) -> int | None:
    if start is None:
        return None
    for i in range(start + 1, end + 1):
        d = _price_direction(bars, i)
        if direction == "UP" and d == "UP":
            return i
        if direction == "DOWN" and d == "DOWN":
            return i
    return None


def _timestamp_discontinuities(
    bars: Sequence[Mapping[str, Any]],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(max(start + 1, 1), end + 1):
        prev = str(bars[i - 1].get("timestamp") or "")
        cur = str(bars[i].get("timestamp") or "")
        try:
            pdt = datetime.fromisoformat(prev.replace("Z", "+00:00"))
            cdt = datetime.fromisoformat(cur.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta = (cdt - pdt).total_seconds()
        if delta != 60.0:
            out.append({
                "previous_timestamp": prev,
                "timestamp": cur,
                "delta_seconds": delta,
                "interpretation": "SESSION_RECESS_OR_SOURCE_GAP_NOT_INFERRED",
            })
    return out


def _formation_sequence(
    runs: Sequence[Mapping[str, Any]],
    *,
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    prior_added = False
    for run in runs:
        rs = int(run.get("start_index", -1))
        re = int(run.get("end_index", -1))
        if re < start:
            if not prior_added or re >= int(selected[-1].get("end_index", -1)):
                prior = {
                    "role": "PRIOR_CONDITION_RUN",
                    "start_index": rs,
                    "end_index": re,
                    "start_timestamp": run.get("start_timestamp"),
                    "end_timestamp": run.get("end_timestamp"),
                    "row_count": run.get("row_count"),
                    "state_key": run.get("state_key"),
                    "state": run.get("state"),
                    "start_close": run.get("start_close"),
                    "end_close": run.get("end_close"),
                }
                if selected and selected[-1].get("role") == "PRIOR_CONDITION_RUN":
                    selected[-1] = prior
                else:
                    selected.append(prior)
                prior_added = True
            continue
        if rs > end:
            break
        selected.append({
            "role": "EVENT_FORMATION_RUN",
            "start_index": rs,
            "end_index": re,
            "start_timestamp": run.get("start_timestamp"),
            "end_timestamp": run.get("end_timestamp"),
            "row_count": run.get("row_count"),
            "state_key": run.get("state_key"),
            "state": run.get("state"),
            "start_close": run.get("start_close"),
            "end_close": run.get("end_close"),
        })
    return selected


def _resolution_semantics(kind: str, status: str, ts: str | None) -> dict[str, str | None]:
    fail = recovery = rebase = invalidation = None
    if status in {
        "FAILED_BELOW_RECOVERY_START_CLOSE",
        "FLOW_LEFT_BUY_BEFORE_ADVANCE",
        "FLOW_LEFT_SELL_BEFORE_DECLINE",
        "SELL_FLOW_PRICE_DECLINE",
    }:
        fail = ts
    if status in {"PULLBACK_START_CLOSE_RECLAIMED", "OPEN_RECLAIMED"}:
        recovery = ts
    if status in {
        "RECOVERY_EXTENDED_TO_NEW_PRESTART_RUNNING_HIGH",
        "PULLBACK_EXTENDED_TO_NEW_PRESTART_RUNNING_LOW",
    }:
        rebase = ts
    if status in {
        "FAILED_BELOW_RECOVERY_START_CLOSE",
        "PULLBACK_START_CLOSE_RECLAIMED",
        "OPEN_RECLAIMED",
        "BUY_FLOW_PRICE_ADVANCE",
        "FLOW_LEFT_BUY_BEFORE_ADVANCE",
        "SELL_FLOW_PRICE_DECLINE",
        "FLOW_LEFT_SELL_BEFORE_DECLINE",
    }:
        invalidation = ts
    if kind == "BUY_NONRESPONSE_WINDOW" and status == "BUY_FLOW_PRICE_ADVANCE":
        recovery = ts
    return {
        "fail_time": fail,
        "recovery_time": recovery,
        "rebase_or_transformation_time": rebase,
        "invalidation_time": invalidation,
    }


def _critical_evidence(
    bars: Sequence[Mapping[str, Any]],
    indices: Mapping[str, int | None],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for role, index in indices.items():
        if index is None or index < 0 or index >= len(bars):
            out[role] = None
        else:
            out[role] = _snapshot(bars[index], index)
    return out


def enrich_behavior_lifecycle(
    *,
    bars: Sequence[Mapping[str, Any]],
    full_envelope: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
    journeys: Sequence[Mapping[str, Any]],
    source: str,
    ticker: str,
    trading_date: str,
    carry_in: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session_open = _safe_float(bars[0].get("open")) if bars else None
    records: list[dict[str, Any]] = []

    for ordinal, raw_journey in enumerate(journeys, 1):
        journey = dict(raw_journey)
        kind = str(journey.get("journey_kind") or "UNKNOWN")
        start, end, right_censored, resolution_ts = _journey_bounds(bars, journey)
        resolution = dict(journey.get("hindsight_resolution") or {})
        resolution_status = str(resolution.get("resolution_status") or "UNKNOWN")
        direction = _direction(kind)
        confirmation = _first_confirmation(
            kind,
            bars,
            start,
            end,
            session_open=session_open,
        )
        peak_first, peak_last, trough_first, trough_last = _extreme_indices(bars, start, end)
        if direction == "UP":
            extreme = peak_first
        elif direction == "DOWN":
            extreme = trough_first
        else:
            extreme = peak_first if peak_first is not None else trough_first

        weakening = _first_counter_move(bars, start=start, end=end, direction=direction)
        resumption = _first_resumption(bars, start=weakening, end=end, direction=direction)
        resolved = _resolution_semantics(kind, resolution_status, resolution_ts)

        if direction == "DOWN" and resolved["recovery_time"] is None:
            resolved["recovery_time"] = _timestamp(bars[weakening]) if weakening is not None else None
        elif direction == "UP" and resolved["recovery_time"] is None and resumption is not None:
            resolved["recovery_time"] = _timestamp(bars[resumption])

        event_end_time: str | None
        if right_censored:
            event_end_time = "OPEN"
        else:
            event_end_time = resolution_ts or _timestamp(bars[end])

        prior_bar = bars[start - 1] if start > 0 else None
        prior_from_carry = None
        if start == 0 and carry_in:
            prior_from_carry = (
                dict(carry_in.get("last_source_supported_observation_state") or {})
                or dict(carry_in)
            )

        timing = {
            "precursor_start_time": None,
            "first_observed_time": _timestamp(bars[start]),
            "event_start_time": _timestamp(bars[start]),
            "first_detectable_time": _timestamp(bars[start]),
            "change_point_time": _timestamp(bars[start]),
            "known_at_time": _timestamp(bars[start]),
            "confirm_time": _timestamp(bars[confirmation]) if confirmation is not None else None,
            "peak_time": _timestamp(bars[peak_first]) if peak_first is not None else None,
            "trough_time": _timestamp(bars[trough_first]) if trough_first is not None else None,
            "extreme_time": _timestamp(bars[extreme]) if extreme is not None else None,
            "weakening_time": _timestamp(bars[weakening]) if weakening is not None else None,
            "fail_time": resolved["fail_time"],
            "recovery_time": resolved["recovery_time"],
            "rebase_or_transformation_time": resolved["rebase_or_transformation_time"],
            "invalidation_time": resolved["invalidation_time"],
            "event_end_time": event_end_time,
            "last_observed_time": _timestamp(bars[end]),
            "follow_through_end_time": _timestamp(bars[-1]) if (bars and not right_censored) else None,
        }
        missing_fields = [name for name in LIFECYCLE_TIMING_FIELDS if name not in timing]
        if missing_fields:
            raise RuntimeError(f"V32_LIFECYCLE_CONTRACT_FIELD_MISSING:{missing_fields}")

        critical_indices = {
            "event_start": start,
            "confirmation": confirmation,
            "peak_first": peak_first,
            "peak_last": peak_last,
            "trough_first": trough_first,
            "trough_last": trough_last,
            "weakening": weakening,
            "resumption": resumption,
            "event_last_observed": end,
        }
        rec = {
            "schema": SCHEMA,
            "source": source,
            "ticker": ticker,
            "date": trading_date,
            "journey_id": _stable_id(source, ticker, trading_date, kind, str(start), str(ordinal)),
            "journey_ordinal": ordinal,
            "journey_kind": kind,
            "directional_role": direction,
            "causal_start": dict(journey.get("causal_start") or {}),
            "hindsight_resolution": resolution,
            "timing": timing,
            "timing_contract_fields": list(LIFECYCLE_TIMING_FIELDS),
            "timing_contract_complete": True,
            "timing_values_may_be_null_when_not_source_proven_or_not_applicable": True,
            "prior_condition": {
                "regular_prior_bar": _snapshot(prior_bar, start - 1) if prior_bar is not None else None,
                "cross_date_carry_if_start_at_first_regular_bar": prior_from_carry,
            },
            "precursor": {
                "status": "NOT_ASSERTED_WITHOUT_SOURCE_SUPPORTED_EVENT_SPECIFIC_PRECURSOR",
                "start_time": None,
                "pre_event_context_is_preserved_separately": True,
            },
            "formation_sequence": _formation_sequence(runs, start=start, end=end),
            "critical_evidence": _critical_evidence(bars, critical_indices),
            "timestamp_discontinuities": _timestamp_discontinuities(bars, start, end),
            "right_censored_open": right_censored,
            "event_history_immutable": True,
            "future_resolution_not_used_to_backdate_start": True,
            "manual_label_used_as_target": False,
            "arbitrary_threshold_added": False,
            "follow_through": {
                "status": (
                    "POST_RESOLUTION_CONTEXT_OBSERVED_TO_REGULAR_SOURCE_END_NOT_ASSERTED_COMPLETE"
                    if not right_censored and bars
                    else "NOT_AVAILABLE_WHILE_EVENT_OPEN"
                ),
                "context_end_time": _timestamp(bars[-1]) if bars and not right_censored else None,
            },
            "full_source_supported_terminal_context": _snapshot(
                full_envelope[-1], len(full_envelope) - 1
            ) if full_envelope else None,
        }
        records.append(rec)

    # Objective temporal connectivity only. It does NOT force a semantic merge.
    chains: list[list[int]] = []
    bounds: list[tuple[int, int]] = []
    for rec in records:
        start = int((rec.get("causal_start") or {}).get("index", -1))
        last = rec.get("critical_evidence", {}).get("event_last_observed") or {}
        end = int(last.get("index", start))
        bounds.append((start, end))
    for i, (start, end) in enumerate(bounds):
        if not chains:
            chains.append([i])
            continue
        last_chain = chains[-1]
        chain_end = max(bounds[j][1] for j in last_chain)
        if start <= chain_end + 1:
            last_chain.append(i)
        else:
            chains.append([i])
    for chain_no, members in enumerate(chains, 1):
        cid = _stable_id(source, ticker, trading_date, "TEMPORAL_CHAIN", str(chain_no))
        for idx in members:
            records[idx]["temporal_connected_chain"] = {
                "chain_id": cid,
                "member_count": len(members),
                "member_ordinals": [records[j]["journey_ordinal"] for j in members],
                "semantic_merge_asserted": False,
                "reason": "OVERLAPPING_OR_ADJACENT_SOURCE_SUPPORTED_EVENT_WINDOWS",
            }

    close_values = [_safe_float(x.get("close")) for x in bars]
    close_values = [x for x in close_values if x is not None]
    total_volume = sum((_safe_float(x.get("volume")) or 0.0) for x in bars) if bars else 0.0
    total_value = sum((_safe_float(x.get("trade_value")) or 0.0) for x in bars) if bars else 0.0
    unchanged_with_activity = 0
    for i in range(1, len(bars)):
        cur = _safe_float(bars[i].get("close"))
        prev = _safe_float(bars[i - 1].get("close"))
        vol = _safe_float(bars[i].get("volume"))
        value = _safe_float(bars[i].get("trade_value"))
        if cur is not None and prev is not None and cur == prev and ((vol or 0.0) > 0.0 or (value or 0.0) > 0.0):
            unchanged_with_activity += 1

    lifecycle_counts = Counter(str(x.get("journey_kind") or "UNKNOWN") for x in records)
    day_profile = {
        "schema": SCHEMA,
        "source": source,
        "ticker": ticker,
        "date": trading_date,
        "regular_bar_count": len(bars),
        "full_source_observation_count": len(full_envelope),
        "first_regular_observation": _snapshot(bars[0], 0) if bars else None,
        "last_regular_observation": _snapshot(bars[-1], len(bars) - 1) if bars else None,
        "last_source_supported_observation": _snapshot(
            full_envelope[-1], len(full_envelope) - 1
        ) if full_envelope else None,
        "cross_date_prior_condition": dict(carry_in or {}) if carry_in else None,
        "journey_count": len(records),
        "journey_kind_counts": dict(sorted(lifecycle_counts.items())),
        "open_right_censored_journey_count": sum(int(bool(x.get("right_censored_open"))) for x in records),
        "no_forced_event": len(records) == 0,
        "observation_only_day_preserved": len(records) == 0,
        "distinct_regular_close_count": len(set(close_values)),
        "regular_first_close": close_values[0] if close_values else None,
        "regular_last_close": close_values[-1] if close_values else None,
        "regular_high": max((_safe_float(x.get("high")) for x in bars), default=None),
        "regular_low": min((_safe_float(x.get("low")) for x in bars), default=None),
        "total_regular_volume": total_volume,
        "total_regular_trade_value": total_value,
        "unchanged_close_with_activity_observation_count": unchanged_with_activity,
        "lifecycle_contract": {
            "prior_condition": True,
            "precursor_slot": True,
            "initiation_event_start": True,
            "first_observed": True,
            "first_detectable": True,
            "change_point": True,
            "known_at": True,
            "confirmation": True,
            "peak_trough_extreme": True,
            "weakening": True,
            "recovery": True,
            "failure": True,
            "rebase_or_transformation": True,
            "invalidation": True,
            "event_end_or_open": True,
            "last_observed": True,
            "follow_through_context": True,
            "formation_sequence": True,
            "source_gap_uncertainty": True,
            "causal_hindsight_separation": True,
            "connected_sequence_context": True,
            "zero_one_multiple_journey_allowed": True,
            "manual_hidden_target": False,
            "arbitrary_threshold": False,
        },
    }
    return day_profile, records
