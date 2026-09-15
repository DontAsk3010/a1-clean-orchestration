from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .handbook_candidates import (
    TRUE,
    CandidateParams,
    evaluate_intraday_candidates,
    evaluate_progressive_h2_h1,
)


FIELD_ALIASES = {
    "open": ("RAW_OPEN", "RAW_Open", "Open", "OPEN"),
    "high": ("RAW_HIGH", "RAW_High", "High", "HIGH"),
    "low": ("RAW_LOW", "RAW_Low", "Low", "LOW"),
    "close": ("RAW_CLOSE", "RAW_Close", "Close", "CLOSE"),
    "volume": ("RAW_VOLUME", "RAW_Volume", "Volume", "VOLUME"),
    "trade_value": ("RAW_AUX2_PHYSICAL", "RAW_Aux2", "RAW_AUX2", "Aux2", "AUX2"),
    "nbss": (
        "RAW_OPENINT_PHYSICAL",
        "RAW_OPENINTEREST_PHYSICAL",
        "RAW_OpenInterest",
        "RAW_OPENINTEREST",
        "OpenInterest",
        "OPENINTEREST",
    ),
    "regular_session1": ("CLK_REGULAR_SESSION1_FLAG",),
    "regular_session2": ("CLK_REGULAR_SESSION2_FLAG",),
    "symbol_is_index": ("SYMBOL_IS_INDEX",),
    "continuous_quotations": ("SYMBOL_CONTINUOUS_QUOTATIONS_FLAG",),
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


def _flag(row: Mapping[str, str], field: str) -> bool:
    value = _num(row, field)
    return value is not None and value != 0.0


def packet_to_formula_bars(packet) -> tuple[list[dict[str, Any]], dict[str, str]]:
    mapping = {logical: _resolve(packet.header, logical) for logical in FIELD_ALIASES}
    bars: list[dict[str, Any]] = []
    for row, ts in zip(packet.rows, packet.timestamps, strict=True):
        nbss = _num(row, mapping["nbss"])
        trade_value = _num(row, mapping["trade_value"])
        is_index = _flag(row, mapping["symbol_is_index"])
        continuous = _flag(row, mapping["continuous_quotations"])
        regular_session1 = _flag(row, mapping["regular_session1"])
        regular_session2 = _flag(row, mapping["regular_session2"])
        regular_clock = regular_session1 or regular_session2
        ordinary_regular_stock = bool((not is_index) and continuous and regular_clock)

        # Current-clean retains physical zero.  For this candidate replay, non-zero
        # NBSS is positive evidence that a signed-flow observation is populated.
        # Physical zero remains UNKNOWN until an independent availability fact is
        # bound; zero is never silently converted into neutral flow.
        flow_available = bool(trade_value is not None and nbss is not None and nbss != 0.0)

        bars.append(
            {
                "trading_date": packet.identity.trading_date,
                "open": _num(row, mapping["open"]),
                "high": _num(row, mapping["high"]),
                "low": _num(row, mapping["low"]),
                "close": _num(row, mapping["close"]),
                "volume": _num(row, mapping["volume"]),
                "trade_value": trade_value,
                "nbss": nbss,
                "flow_available": flow_available,
                "mechanism_eligible": bool(ordinary_regular_stock and flow_available),
                "session_eligible": ordinary_regular_stock,
                "regular_session1": bool(regular_session1),
                "regular_session2": bool(regular_session2),
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
    entry_raw = bars[index].get("close")
    if entry_raw is None or float(entry_raw) <= 0:
        return
    entry = float(entry_raw)
    event_date = str(bars[index].get("trading_date") or "")
    for horizon in horizons:
        key = str(horizon)
        row = bucket.setdefault(key, _blank_horizon())
        row["event_count"] += 1
        end = index + horizon
        if end >= len(bars):
            continue
        evaluation = bars[index + 1 : end + 1]
        if any(str(bar.get("trading_date") or "") != event_date for bar in evaluation):
            continue
        forward_raw = bars[end].get("close")
        if forward_raw is None:
            continue
        highs = [float(bar["high"]) for bar in evaluation if bar.get("high") is not None]
        lows = [float(bar["low"]) for bar in evaluation if bar.get("low") is not None]
        if not highs or not lows:
            continue
        forward_close = float(forward_raw)
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
    raw_row_count = 0
    formula_row_count = 0
    field_mappings: set[str] = set()

    for manifest_row, packet in reader.iter_packets():
        if max_packets and packet_count >= max_packets:
            break
        all_bars, mapping = packet_to_formula_bars(packet)
        field_mappings.add(json.dumps(mapping, sort_keys=True))
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        states = evaluate_intraday_candidates(bars, params)
        packet_count += 1
        raw_row_count += len(all_bars)
        formula_row_count += len(bars)

        for formula_id in INTRADAY_FORMULAS:
            previous_true = False
            for i, state_row in enumerate(states):
                state = state_row["states"][formula_id]
                state_counts[formula_id][state] += 1
                is_true = state == TRUE
                if is_true and not previous_true:
                    _record_event(metrics[formula_id], bars, i, horizons)
                previous_true = is_true

        if bars:
            ticker_sessions[str(packet.identity.ticker)].append(
                {
                    "trading_date": str(packet.identity.trading_date),
                    "bars": bars,
                    "states": states,
                }
            )

    progressive_metrics: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    progressive_counts = {"TRUE": 0, "FALSE": 0, "UNKNOWN": 0}
    progressive_outcomes = {
        "TRUE": {"sessions": 0, "positive_close": 0, "sum_close_return": 0.0},
        "FALSE": {"sessions": 0, "positive_close": 0, "sum_close_return": 0.0},
        "UNKNOWN": {"sessions": 0, "positive_close": 0, "sum_close_return": 0.0},
    }
    for ticker, sessions in ticker_sessions.items():
        sessions.sort(key=lambda row: row["trading_date"])
        daily_inputs = []
        for session in sessions:
            bars = session["bars"]
            states = session["states"]
            closes = [float(bar["close"]) for bar in bars if bar.get("close") is not None]
            highs = [float(bar["high"]) for bar in bars if bar.get("high") is not None]
            lows = [float(bar["low"]) for bar in bars if bar.get("low") is not None]
            daily_inputs.append(
                {
                    "trading_date": session["trading_date"],
                    "open": closes[0] if closes else None,
                    "high": max(highs) if highs else None,
                    "low": min(lows) if lows else None,
                    "close": closes[-1] if closes else None,
                    "states": states,
                }
            )
        progressive_rows = evaluate_progressive_h2_h1(daily_inputs, params)
        for idx, state_row in enumerate(progressive_rows):
            state = state_row["state"]
            progressive_counts[state] += 1
            bars = sessions[idx]["bars"]
            if bars:
                first_close = bars[0].get("close")
                last_close = bars[-1].get("close")
                if first_close not in (None, 0.0) and last_close is not None:
                    ret = float(last_close) / float(first_close) - 1.0
                    bucket = progressive_outcomes[state]
                    bucket["sessions"] += 1
                    bucket["positive_close"] += int(ret > 0)
                    bucket["sum_close_return"] += ret

    progressive_summary = {}
    for state, raw in progressive_outcomes.items():
        n = int(raw["sessions"])
        progressive_summary[state] = {
            "sessions": n,
            "positive_close_rate": (float(raw["positive_close"]) / n) if n else None,
            "mean_close_return": (float(raw["sum_close_return"]) / n) if n else None,
        }

    return {
        "schema": "A1_CANDIDATE_FORMULA_REPLAY_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_identity": reader.identity.as_dict(),
        "params": asdict(params),
        "packet_count": packet_count,
        "raw_row_count": raw_row_count,
        "formula_regular_row_count": formula_row_count,
        "field_mappings": [json.loads(item) for item in sorted(field_mappings)],
        "state_counts": state_counts,
        "intraday_first_event_metrics": _finalize(metrics),
        "progressive_state_counts": progressive_counts,
        "progressive_same_day_outcomes": progressive_summary,
        "future_data_used_for_intraday_state": False,
        "future_data_used_only_for_evaluation": True,
        "winner_only_filter_used": False,
        "all_eligible_source_packets_scanned": max_packets == 0,
        "canonical_vwap_synthesized": False,
        "final_or_canonical_claim": False,
    }


def _parse_horizons(value: str) -> list[int]:
    items = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not items or any(item < 1 for item in items):
        raise argparse.ArgumentTypeError("horizons must be positive integers")
    return items


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-candidate-formula-replay")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--horizons", type=_parse_horizons, required=True)
    parser.add_argument("--max-packets", type=int, default=0)
    parser.add_argument("--effort-lookback", type=int, required=True)
    parser.add_argument("--progress-lookback", type=int, required=True)
    parser.add_argument("--high-lookback", type=int, required=True)
    parser.add_argument("--recovery-lookback", type=int, required=True)
    parser.add_argument("--low-stabilization-bars", type=int, required=True)
    parser.add_argument("--early-checkpoint-bar", type=int, required=True)
    parser.add_argument("--late-lift-min-bar", type=int, required=True)
    args = parser.parse_args(argv)

    params = CandidateParams(
        effort_lookback=args.effort_lookback,
        progress_lookback=args.progress_lookback,
        high_lookback=args.high_lookback,
        recovery_lookback=args.recovery_lookback,
        low_stabilization_bars=args.low_stabilization_bars,
        early_checkpoint_bar=args.early_checkpoint_bar,
        late_lift_min_bar=args.late_lift_min_bar,
    )
    result = replay_source(
        source_name=args.source_name,
        params=params,
        horizons=args.horizons,
        max_packets=args.max_packets,
    )
    result = {**result, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    if not safe_request:
        raise SystemExit("REQUEST_ID_HAS_NO_SAFE_CHARACTERS")
    uploaded = store.upsert_json(
        name=f"CANDIDATE_FORMULA_REPLAY__{safe_request}.json",
        obj=result,
    )
    print(json.dumps({"pass": True, "result": result, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
