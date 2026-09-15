from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import time
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .handbook_candidates import (
    TRUE,
    CandidateParams,
    evaluate_intraday_candidates,
    evaluate_progressive_h2_h1,
)


FIELD_ALIASES = {
    "open": ("RAW_Open", "RAW_OPEN", "Open", "OPEN"),
    "high": ("RAW_High", "RAW_HIGH", "High", "HIGH"),
    "low": ("RAW_Low", "RAW_LOW", "Low", "LOW"),
    "close": ("RAW_Close", "RAW_CLOSE", "Close", "CLOSE"),
    "volume": ("RAW_Volume", "RAW_VOLUME", "Volume", "VOLUME"),
    "trade_value": ("RAW_Aux2", "RAW_AUX2", "Aux2", "AUX2"),
    "nbss": ("RAW_OpenInterest", "RAW_OPENINTEREST", "OpenInterest", "OPENINTEREST"),
}

INTRADAY_FORMULAS = (
    "F01A_BUY_STALL_BASIC",
    "F01B_BUY_STALL_STALE_HIGH_EFFORT",
    "F02A_SELL_RESILIENCE_BASIC",
    "F02B_SELL_RESILIENCE_ACCEPTANCE_RENEWAL",
    "F03A_NEW_HIGH_EVENT",
    "F04A_EARLY_STRENGTH_RETAINED",
    "F04B_LATE_LIFT",
    "F05A_SESSION_OPEN_RECOVERY",
    "F05B_CANONICAL_VWAP_RECOVERY",
)


def _resolve(header: Sequence[str], logical: str) -> str:
    aliases = FIELD_ALIASES[logical]
    header_map = {name.casefold(): name for name in header}
    for alias in aliases:
        if alias.casefold() in header_map:
            return header_map[alias.casefold()]
    raise ValueError(f"FORMULA_REPLAY_FIELD_MISSING:{logical}:ALIASES={aliases}:HEADER={tuple(header)}")


def _num(row: Mapping[str, str], field: str) -> float | None:
    raw = row.get(field)
    if raw is None or str(raw).strip() == "":
        return None
    return float(raw)


def packet_to_formula_bars(packet) -> tuple[list[dict[str, Any]], dict[str, str]]:
    mapping = {logical: _resolve(packet.header, logical) for logical in FIELD_ALIASES}
    bars: list[dict[str, Any]] = []
    for row, ts in zip(packet.rows, packet.timestamps, strict=True):
        nbss = _num(row, mapping["nbss"])
        # Conservative historical availability guard: non-zero observed NBSS proves
        # this bar is populated enough for positive/negative effort relations.
        # Zero is NOT assumed neutral without a separate availability fact.
        flow_available = nbss is not None and nbss != 0.0
        regular_clock = time(9, 0) <= ts.time() < time(15, 50)
        session_clock = time(9, 0) <= ts.time() <= time(16, 15)
        bars.append(
            {
                "trading_date": packet.identity.trading_date,
                "open": _num(row, mapping["open"]),
                "high": _num(row, mapping["high"]),
                "low": _num(row, mapping["low"]),
                "close": _num(row, mapping["close"]),
                "volume": _num(row, mapping["volume"]),
                "trade_value": _num(row, mapping["trade_value"]),
                "nbss": nbss,
                "flow_available": flow_available,
                "mechanism_eligible": bool(regular_clock and flow_available),
                "session_eligible": session_clock,
                "canonical_vwap": None,
                "timestamp": ts.isoformat(sep=" "),
            }
        )
    return bars, mapping


def _blank_horizon() -> dict[str, float | int]:
    return {
        "event_count": 0,
        "evaluable_count": 0,
        "positive_forward_count": 0,
        "sum_forward_return": 0.0,
        "sum_mfe": 0.0,
        "sum_mae": 0.0,
    }


def _record_event(
    bucket: dict[str, Any],
    bars: Sequence[Mapping[str, Any]],
    index: int,
    horizons: Sequence[int],
) -> None:
    entry = float(bars[index]["close"])
    for horizon in horizons:
        key = str(horizon)
        row = bucket.setdefault(key, _blank_horizon())
        row["event_count"] += 1
        end = index + horizon
        if end >= len(bars):
            continue
        forward_close = float(bars[end]["close"])
        highs = [float(bar["high"]) for bar in bars[index + 1 : end + 1] if bar.get("high") is not None]
        lows = [float(bar["low"]) for bar in bars[index + 1 : end + 1] if bar.get("low") is not None]
        if not highs or not lows:
            continue
        forward_return = forward_close / entry - 1.0
        row["evaluable_count"] += 1
        row["positive_forward_count"] += int(forward_return > 0)
        row["sum_forward_return"] += forward_return
        row["sum_mfe"] += max(highs) / entry - 1.0
        row["sum_mae"] += min(lows) / entry - 1.0


def _finalize(metrics: Mapping[str, Mapping[str, Mapping[str, float | int]]]) -> dict[str, Any]:
    final: dict[str, Any] = {}
    for formula_id, horizons in metrics.items():
        final[formula_id] = {}
        for horizon, raw in horizons.items():
            n = int(raw["evaluable_count"])
            final[formula_id][horizon] = {
                "event_count": int(raw["event_count"]),
                "evaluable_count": n,
                "positive_forward_count": int(raw["positive_forward_count"]),
                "positive_forward_rate": (float(raw["positive_forward_count"]) / n) if n else None,
                "mean_forward_return": (float(raw["sum_forward_return"]) / n) if n else None,
                "mean_mfe": (float(raw["sum_mfe"]) / n) if n else None,
                "mean_mae": (float(raw["sum_mae"]) / n) if n else None,
            }
    return final


def replay_source(
    *,
    source_name: str,
    params: CandidateParams,
    horizons: Sequence[int],
    max_packets: int = 0,
) -> dict[str, Any]:
    if not source_name:
        raise ValueError("SOURCE_NAME_REQUIRED")
    if not horizons or any(int(value) < 1 for value in horizons):
        raise ValueError("POSITIVE_HORIZONS_REQUIRED")
    if max_packets < 0:
        raise ValueError("MAX_PACKETS_MUST_BE_ZERO_OR_POSITIVE")
    params.validate()

    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    metrics: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    state_counts: dict[str, dict[str, int]] = {
        formula_id: {"TRUE": 0, "FALSE": 0, "UNKNOWN": 0} for formula_id in INTRADAY_FORMULAS
    }
    ticker_sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    packet_count = 0
    row_count = 0
    field_mappings: set[str] = set()

    for manifest_row, packet in reader.iter_packets():
        if max_packets and packet_count >= max_packets:
            break
        bars, mapping = packet_to_formula_bars(packet)
        field_mappings.add(json.dumps(mapping, sort_keys=True))
        states = evaluate_intraday_candidates(bars, params)
        packet_count += 1
        row_count += len(bars)

        for formula_id in INTRADAY_FORMULAS:
            previous_true = False
            for i, state_row in enumerate(states):
                state = state_row["states"][formula_id]
                state_counts[formula_id][state] += 1
                is_true = state == TRUE
                if is_true and not previous_true:
                    _record_event(metrics[formula_id], bars, i, horizons)
                previous_true = is_true

        eligible = [bar for bar in bars if bar["session_eligible"]]
        if eligible:
            ticker_sessions[packet.identity.ticker].append(
                {
                    "trading_date": packet.identity.trading_date,
                    "high": max(float(bar["high"]) for bar in eligible if bar["high"] is not None),
                    "low": min(float(bar["low"]) for bar in eligible if bar["low"] is not None),
                    "close": float(eligible[-1]["close"]),
                    "activity": sum(float(bar["trade_value"] or 0.0) for bar in eligible),
                }
            )

    f06_counts = {
        "F06A_PRICE_PROGRESS": {"TRUE": 0, "FALSE": 0, "UNKNOWN": 0},
        "F06B_PRICE_ACTIVITY_PROGRESS": {"TRUE": 0, "FALSE": 0, "UNKNOWN": 0},
    }
    for sessions in ticker_sessions.values():
        sessions.sort(key=lambda row: str(row["trading_date"]))
        for row in evaluate_progressive_h2_h1(sessions):
            for formula_id in f06_counts:
                f06_counts[formula_id][row[formula_id]] += 1

    return {
        "schema": "A1_CANDIDATE_FORMULA_CAUSAL_REPLAY_RESULT_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_identity": reader.identity.as_dict(),
        "candidate_spec_id": "A1_HANDBOOK_DERIVED_CANDIDATE_FORMULAS_V1",
        "params": asdict(params),
        "forward_horizons_bars": [int(value) for value in horizons],
        "packet_count": packet_count,
        "row_count": row_count,
        "field_mappings_observed": [json.loads(value) for value in sorted(field_mappings)],
        "flow_availability_policy": "NBSS_NONZERO_PROVES_POPULATED_FOR_SIGNED_EFFORT; ZERO_REMAINS_UNKNOWN_WITHOUT_INDEPENDENT_AVAILABILITY",
        "canonical_vwap_policy": "NOT_SYNTHESIZED; VWAP_DEPENDENT_VARIANTS_REMAIN_UNKNOWN",
        "intraday_state_counts": state_counts,
        "intraday_event_forward_metrics": _finalize(metrics),
        "multiday_context_state_counts": f06_counts,
        "outcome_is_evaluation_only_not_formula_input": True,
        "future_data_used_for_candidate_state": False,
        "winner_only_filter_used": False,
        "failed_variants_preserved": True,
    }


def write_result(path: str | Path, result: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
