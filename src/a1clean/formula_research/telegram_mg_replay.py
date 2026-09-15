from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, time
import argparse
import json
import math
from pathlib import Path
from statistics import fmean, median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import (
    FALSE,
    TRUE,
    UNKNOWN,
    CandidateParams,
    evaluate_intraday_candidates,
)

MG_VARIANTS = (
    "MG_A_PATH_PERSISTENCE",
    "MG_B_PATH_VALUE",
    "MG_C_PATH_FLOW",
    "MG_D_PATH_VALUE_FLOW",
    "MG_E_FRESH_PROGRESS",
    "MG_F_ABSORPTION_PATH",
    "MG_G_BUY_RESPONSE_PATH",
    "MG_H_RETAINED_FLOW",
)

COMPONENTS = (
    "UP_PATH",
    "MULTIBAR_PERSISTENCE",
    "BAR_ACCEPTANCE",
    "VALUE_EXPANSION",
    "CONSTRUCTIVE_FLOW",
    "BUY_RESPONSE",
    "SELL_RESILIENCE",
    "ANTI_BUY_STALL",
    "FRESH_HIGH",
    "EARLY_STRENGTH_RETAINED",
)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _tri(value: bool | None) -> str:
    if value is None:
        return UNKNOWN
    return TRUE if value else FALSE


def _as_bool(state: str) -> bool | None:
    if state == TRUE:
        return True
    if state == FALSE:
        return False
    return None


def _and_all(*values: bool | None) -> bool | None:
    if any(value is False for value in values):
        return False
    if all(value is True for value in values):
        return True
    return None


def _or_any(*values: bool | None) -> bool | None:
    if any(value is True for value in values):
        return True
    if all(value is False for value in values):
        return False
    return None


def _prior_floats(
    bars: Sequence[Mapping[str, Any]], index: int, key: str, lookback: int
) -> list[float] | None:
    start = index - lookback
    if start < 0:
        return None
    values = [_num(bars[j].get(key)) for j in range(start, index)]
    if len(values) != lookback or any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _window_floats(
    bars: Sequence[Mapping[str, Any]], index: int, key: str, lookback: int
) -> list[float] | None:
    start = index - lookback + 1
    if start < 0:
        return None
    values = [_num(bars[j].get(key)) for j in range(start, index + 1)]
    if len(values) != lookback or any(value is None for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _dynamic_targets(
    bars: Sequence[Mapping[str, Any]], index: int, lookback: int
) -> tuple[float | None, float | None, float | None]:
    """Research target proxy from causal local range + observed high structure.

    No fixed return percentage is used. The step is the median observed
    high-low range over the causal lookback. TP-1 must clear both current
    price plus one local step and the recent observed high. TP-2 extends one
    additional local step beyond the stronger of TP-1 and the session high
    observed through the current bar.
    """
    close = _num(bars[index].get("close"))
    if close is None or close <= 0:
        return None, None, None
    start = index - lookback + 1
    if start < 0:
        return None, None, None
    window = bars[start : index + 1]
    ranges: list[float] = []
    highs: list[float] = []
    for row in window:
        high = _num(row.get("high"))
        low = _num(row.get("low"))
        if high is None or low is None:
            return None, None, None
        if high < low:
            return None, None, None
        highs.append(high)
        if high > low:
            ranges.append(high - low)
    if not ranges:
        return None, None, None
    step = float(median(ranges))
    if step <= 0:
        return None, None, None
    session_highs = [
        float(row["high"])
        for row in bars[: index + 1]
        if row.get("high") is not None
    ]
    if not session_highs:
        return None, None, None
    recent_high = max(highs)
    session_high = max(session_highs)
    tp1 = max(recent_high, close + step)
    tp2 = max(session_high, tp1) + step
    if not (tp2 > tp1 > close):
        return None, None, None
    return tp1, tp2, step


def _is_publication_slot(timestamp: Any) -> bool:
    if timestamp is None:
        return False
    try:
        dt = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return False
    return dt.time() >= time(9, 0) and dt.minute % 5 == 0


def evaluate_mg_packet(
    bars: Sequence[Mapping[str, Any]], params: CandidateParams
) -> list[dict[str, Any]]:
    """Build causal EARLY_POTENTIAL/MULAI GENIT research variants.

    The variants are combinations of behavior-derived components. They are
    candidate research states only, never canonical/public activation logic.
    """
    params.validate()
    base = evaluate_intraday_candidates(bars, params)
    out: list[dict[str, Any]] = []

    for i, (bar, base_row) in enumerate(zip(bars, base, strict=True)):
        close = _num(bar.get("close"))
        high = _num(bar.get("high"))
        low = _num(bar.get("low"))
        trade_value = _num(bar.get("trade_value"))
        session_open = _num(base_row["measurements"].get("session_open"))

        prior_closes = _prior_floats(bars, i, "close", params.progress_lookback)
        current_close_window = _window_floats(
            bars, i, "close", params.progress_lookback
        )
        prior_values = _prior_floats(bars, i, "trade_value", params.effort_lookback)

        up_path: bool | None = None
        if close is not None and session_open is not None and prior_closes is not None:
            up_path = bool(close > session_open and close >= fmean(prior_closes))

        persistence: bool | None = None
        if current_close_window is not None:
            step_count = len(current_close_window) - 1
            non_down_steps = sum(
                current_close_window[j] >= current_close_window[j - 1]
                for j in range(1, len(current_close_window))
            )
            persistence = bool(
                step_count > 0 and non_down_steps >= math.ceil(step_count / 2)
            )

        acceptance: bool | None = None
        if None not in (close, high, low):
            acceptance = bool(float(close) >= (float(high) + float(low)) / 2.0)

        value_expansion: bool | None = None
        if trade_value is not None and prior_values is not None:
            value_expansion = bool(trade_value > fmean(prior_values))

        haka = _num(base_row["measurements"].get("haka_value_1m"))
        haki = _num(base_row["measurements"].get("haki_value_1m"))
        buy_response: bool | None = None
        if i > 0 and None not in (
            haka,
            haki,
            close,
            high,
            bars[i - 1].get("close"),
            bars[i - 1].get("high"),
        ):
            buy_response = bool(
                float(haka) > float(haki)
                and float(close) > float(bars[i - 1]["close"])
                and float(high) >= float(bars[i - 1]["high"])
            )

        sell_resilience = _as_bool(
            base_row["states"]["F02A_SELL_RESILIENCE_BASIC"]
        )
        constructive_flow = _or_any(buy_response, sell_resilience)

        buy_stall = _as_bool(base_row["states"]["F01A_BUY_STALL_BASIC"])
        anti_stall = None if buy_stall is None else (not buy_stall)
        fresh_high = _as_bool(base_row["states"]["F03A_NEW_HIGH_EVENT"])
        retained = _as_bool(base_row["states"]["F04A_EARLY_STRENGTH_RETAINED"])

        a = _and_all(up_path, persistence, acceptance)
        b = _and_all(a, value_expansion)
        c = _and_all(a, constructive_flow, anti_stall)
        d = _and_all(b, constructive_flow, anti_stall)
        e = _and_all(d, fresh_high)
        f = _and_all(b, sell_resilience, anti_stall)
        g = _and_all(b, buy_response, anti_stall)
        h = _and_all(d, retained)

        tp1, tp2, target_step = _dynamic_targets(
            bars, i, max(params.high_lookback, params.progress_lookback)
        )

        components = {
            "UP_PATH": _tri(up_path),
            "MULTIBAR_PERSISTENCE": _tri(persistence),
            "BAR_ACCEPTANCE": _tri(acceptance),
            "VALUE_EXPANSION": _tri(value_expansion),
            "CONSTRUCTIVE_FLOW": _tri(constructive_flow),
            "BUY_RESPONSE": _tri(buy_response),
            "SELL_RESILIENCE": _tri(sell_resilience),
            "ANTI_BUY_STALL": _tri(anti_stall),
            "FRESH_HIGH": _tri(fresh_high),
            "EARLY_STRENGTH_RETAINED": _tri(retained),
        }
        variants = {
            "MG_A_PATH_PERSISTENCE": _tri(a),
            "MG_B_PATH_VALUE": _tri(b),
            "MG_C_PATH_FLOW": _tri(c),
            "MG_D_PATH_VALUE_FLOW": _tri(d),
            "MG_E_FRESH_PROGRESS": _tri(e),
            "MG_F_ABSORPTION_PATH": _tri(f),
            "MG_G_BUY_RESPONSE_PATH": _tri(g),
            "MG_H_RETAINED_FLOW": _tri(h),
        }
        out.append(
            {
                "index": i,
                "timestamp": bar.get("timestamp"),
                "trading_date": bar.get("trading_date"),
                "components": components,
                "variants": variants,
                "targets": {
                    "tp1": tp1,
                    "tp2": tp2,
                    "local_range_step": target_step,
                },
                "publication_slot": _is_publication_slot(bar.get("timestamp")),
            }
        )
    return out


def _blank_metric() -> dict[str, float | int]:
    return {
        "event_count": 0,
        "evaluable_count": 0,
        "positive_forward_count": 0,
        "failure_close_nonpositive_count": 0,
        "sum_forward_return": 0.0,
        "sum_mfe": 0.0,
        "sum_mae": 0.0,
        "tp1_evaluable_count": 0,
        "tp1_hit_count": 0,
        "tp1_hit_bars_sum": 0,
        "tp2_evaluable_count": 0,
        "tp2_hit_count": 0,
        "tp2_hit_bars_sum": 0,
    }


def _record(
    bucket: dict[str, dict[str, float | int]],
    bars: Sequence[Mapping[str, Any]],
    mg_rows: Sequence[Mapping[str, Any]],
    index: int,
    horizons: Sequence[int],
) -> None:
    close = _num(bars[index].get("close"))
    if close is None or close <= 0:
        return
    event_date = str(bars[index].get("trading_date") or "")
    tp1 = _num(mg_rows[index]["targets"].get("tp1"))
    tp2 = _num(mg_rows[index]["targets"].get("tp2"))

    for horizon in horizons:
        key = str(int(horizon))
        row = bucket.setdefault(key, _blank_metric())
        row["event_count"] += 1
        end = index + int(horizon)
        if end >= len(bars):
            continue
        evaluation = bars[index + 1 : end + 1]
        if any(str(bar.get("trading_date") or "") != event_date for bar in evaluation):
            continue
        highs = [_num(bar.get("high")) for bar in evaluation]
        lows = [_num(bar.get("low")) for bar in evaluation]
        forward = _num(bars[end].get("close"))
        if forward is None or any(value is None for value in highs + lows):
            continue
        high_values = [float(value) for value in highs if value is not None]
        low_values = [float(value) for value in lows if value is not None]
        forward_return = float(forward) / close - 1.0
        row["evaluable_count"] += 1
        row["positive_forward_count"] += int(forward_return > 0)
        row["failure_close_nonpositive_count"] += int(forward_return <= 0)
        row["sum_forward_return"] += forward_return
        row["sum_mfe"] += max(high_values) / close - 1.0
        row["sum_mae"] += min(low_values) / close - 1.0

        if tp1 is not None:
            row["tp1_evaluable_count"] += 1
            for offset, future_bar in enumerate(evaluation, start=1):
                future_high = _num(future_bar.get("high"))
                if future_high is not None and future_high >= tp1:
                    row["tp1_hit_count"] += 1
                    row["tp1_hit_bars_sum"] += offset
                    break
        if tp2 is not None:
            row["tp2_evaluable_count"] += 1
            for offset, future_bar in enumerate(evaluation, start=1):
                future_high = _num(future_bar.get("high"))
                if future_high is not None and future_high >= tp2:
                    row["tp2_hit_count"] += 1
                    row["tp2_hit_bars_sum"] += offset
                    break


def _finalize(
    metrics: Mapping[str, Mapping[str, Mapping[str, float | int]]]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variant, horizons in metrics.items():
        out[variant] = {}
        for horizon, raw in horizons.items():
            n = int(raw["evaluable_count"])
            tp1_n = int(raw["tp1_evaluable_count"])
            tp2_n = int(raw["tp2_evaluable_count"])
            out[variant][horizon] = {
                "event_count": int(raw["event_count"]),
                "evaluable_count": n,
                "positive_forward_count": int(raw["positive_forward_count"]),
                "positive_forward_rate": (
                    float(raw["positive_forward_count"]) / n if n else None
                ),
                "failure_close_nonpositive_rate": (
                    float(raw["failure_close_nonpositive_count"]) / n if n else None
                ),
                "mean_forward_return": (
                    float(raw["sum_forward_return"]) / n if n else None
                ),
                "mean_mfe": float(raw["sum_mfe"]) / n if n else None,
                "mean_mae": float(raw["sum_mae"]) / n if n else None,
                "tp1_evaluable_count": tp1_n,
                "tp1_hit_count": int(raw["tp1_hit_count"]),
                "tp1_hit_rate": (
                    float(raw["tp1_hit_count"]) / tp1_n if tp1_n else None
                ),
                "tp1_mean_bars_to_hit": (
                    float(raw["tp1_hit_bars_sum"]) / int(raw["tp1_hit_count"])
                    if int(raw["tp1_hit_count"])
                    else None
                ),
                "tp2_evaluable_count": tp2_n,
                "tp2_hit_count": int(raw["tp2_hit_count"]),
                "tp2_hit_rate": (
                    float(raw["tp2_hit_count"]) / tp2_n if tp2_n else None
                ),
                "tp2_mean_bars_to_hit": (
                    float(raw["tp2_hit_bars_sum"]) / int(raw["tp2_hit_count"])
                    if int(raw["tp2_hit_count"])
                    else None
                ),
            }
    return out


def replay_mg_source(
    *,
    source_name: str,
    params: CandidateParams,
    horizons: Sequence[int],
    max_packets: int = 0,
) -> dict[str, Any]:
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)

    first_event_metrics: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    snapshot_metrics: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    baseline_metrics: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    state_counts = {
        variant: {TRUE: 0, FALSE: 0, UNKNOWN: 0} for variant in MG_VARIANTS
    }
    component_counts = {
        component: {TRUE: 0, FALSE: 0, UNKNOWN: 0} for component in COMPONENTS
    }
    match_tickers = {variant: set() for variant in MG_VARIANTS}
    match_ticker_days = {variant: set() for variant in MG_VARIANTS}
    eligible_tickers: set[str] = set()
    eligible_ticker_days: set[str] = set()
    packet_count = 0
    raw_row_count = 0
    formula_row_count = 0
    publication_slot_count = 0
    target_available_count = 0
    target_unknown_count = 0
    sample_outputs: list[dict[str, Any]] = []
    previous_close_by_ticker: dict[str, float] = {}

    for manifest_row, packet in reader.iter_packets():
        if max_packets and packet_count >= max_packets:
            break
        all_bars, _mapping = packet_to_formula_bars(packet)
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        packet_count += 1
        raw_row_count += len(all_bars)
        formula_row_count += len(bars)
        ticker = str(packet.identity.ticker)
        trading_date = str(packet.identity.trading_date)
        if bars:
            eligible_tickers.add(ticker)
            eligible_ticker_days.add(f"{trading_date}|{ticker}")

        mg_rows = evaluate_mg_packet(bars, params)
        prev_close = previous_close_by_ticker.get(ticker)

        for component in COMPONENTS:
            for row in mg_rows:
                component_counts[component][row["components"][component]] += 1

        previous_true = {variant: False for variant in MG_VARIANTS}
        for i, row in enumerate(mg_rows):
            if row["targets"]["tp1"] is None or row["targets"]["tp2"] is None:
                target_unknown_count += 1
            else:
                target_available_count += 1

            if row["publication_slot"]:
                publication_slot_count += 1
                _record(
                    baseline_metrics["BASELINE_ALL_VALID_5M_SLOTS"],
                    bars,
                    mg_rows,
                    i,
                    horizons,
                )

            for variant in MG_VARIANTS:
                state = row["variants"][variant]
                state_counts[variant][state] += 1
                is_true = state == TRUE
                if is_true:
                    match_tickers[variant].add(ticker)
                    match_ticker_days[variant].add(f"{trading_date}|{ticker}")
                if is_true and not previous_true[variant]:
                    _record(first_event_metrics[variant], bars, mg_rows, i, horizons)
                if is_true and row["publication_slot"]:
                    _record(snapshot_metrics[variant], bars, mg_rows, i, horizons)
                    if len(sample_outputs) < 200:
                        close = _num(bars[i].get("close"))
                        chg_pct = (
                            (close / prev_close - 1.0) * 100.0
                            if close is not None and prev_close not in (None, 0.0)
                            else None
                        )
                        sample_outputs.append(
                            {
                                "variant": variant,
                                "trading_date": trading_date,
                                "as_of": bars[i].get("timestamp"),
                                "CODE": ticker,
                                "PRICE": close,
                                "CHG%": chg_pct,
                                "TP-1": row["targets"]["tp1"],
                                "TP-2": row["targets"]["tp2"],
                            }
                        )
                previous_true[variant] = is_true

        closes = [
            float(bar["close"])
            for bar in bars
            if bar.get("close") is not None and float(bar["close"]) > 0
        ]
        if closes:
            previous_close_by_ticker[ticker] = closes[-1]

    coverage = {}
    for variant in MG_VARIANTS:
        coverage[variant] = {
            "unique_tickers": len(match_tickers[variant]),
            "unique_ticker_days": len(match_ticker_days[variant]),
            "eligible_ticker_share": (
                len(match_tickers[variant]) / len(eligible_tickers)
                if eligible_tickers
                else None
            ),
            "eligible_ticker_day_share": (
                len(match_ticker_days[variant]) / len(eligible_ticker_days)
                if eligible_ticker_days
                else None
            ),
        }

    return {
        "schema": "A1_TELEGRAM_MG_CANDIDATE_REPLAY_RESULT_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "telegram_family": "EARLY_POTENTIAL",
        "telegram_public_name": "MULAI_GENIT",
        "telegram_output_contract": "CODE | PRICE | CHG% | TP-1 | TP-2",
        "source_identity": reader.identity.as_dict(),
        "params": asdict(params),
        "mg_variant_definitions": {
            "MG_A_PATH_PERSISTENCE": "UP_PATH + MULTIBAR_PERSISTENCE + BAR_ACCEPTANCE",
            "MG_B_PATH_VALUE": "MG_A + VALUE_EXPANSION",
            "MG_C_PATH_FLOW": "MG_A + CONSTRUCTIVE_FLOW + ANTI_BUY_STALL",
            "MG_D_PATH_VALUE_FLOW": "MG_B + CONSTRUCTIVE_FLOW + ANTI_BUY_STALL",
            "MG_E_FRESH_PROGRESS": "MG_D + FRESH_HIGH",
            "MG_F_ABSORPTION_PATH": "MG_B + SELL_RESILIENCE + ANTI_BUY_STALL",
            "MG_G_BUY_RESPONSE_PATH": "MG_B + BUY_RESPONSE + ANTI_BUY_STALL",
            "MG_H_RETAINED_FLOW": "MG_D + EARLY_STRENGTH_RETAINED",
        },
        "dynamic_target_definition": {
            "basis": "CAUSAL_LOCAL_MEDIAN_BAR_RANGE_PLUS_OBSERVED_HIGH_STRUCTURE",
            "lookback": max(params.high_lookback, params.progress_lookback),
            "TP1": "max(recent_observed_high, current_close + local_median_range_step)",
            "TP2": "max(session_high_so_far, TP1) + local_median_range_step",
            "fixed_percentage_used": False,
        },
        "forward_horizons_regular_bars": [int(value) for value in horizons],
        "packet_count": packet_count,
        "raw_row_count": raw_row_count,
        "formula_regular_row_count": formula_row_count,
        "eligible_ticker_count": len(eligible_tickers),
        "eligible_ticker_day_count": len(eligible_ticker_days),
        "publication_slot_count": publication_slot_count,
        "target_available_row_count": target_available_count,
        "target_unknown_row_count": target_unknown_count,
        "component_state_counts": component_counts,
        "variant_state_counts": state_counts,
        "variant_coverage": coverage,
        "first_detectable_event_metrics": _finalize(first_event_metrics),
        "telegram_5m_snapshot_metrics": _finalize(snapshot_metrics),
        "baseline_5m_snapshot_metrics": _finalize(baseline_metrics),
        "sample_telegram_outputs": sample_outputs,
        "future_data_used_for_candidate_state": False,
        "future_data_used_only_for_evaluation": True,
        "winner_only_filter_used": False,
        "all_eligible_source_packets_scanned": max_packets == 0,
        "failed_and_worse_variants_preserved": True,
        "canonical_vwap_synthesized": False,
        "final_or_canonical_claim": False,
    }


def _parse_horizons(value: str) -> list[int]:
    items = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not items or any(item < 1 for item in items):
        raise argparse.ArgumentTypeError("horizons must be positive integers")
    return items


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-candidate-replay")
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
    result = replay_mg_source(
        source_name=args.source_name,
        params=params,
        horizons=args.horizons,
        max_packets=args.max_packets,
    )
    result = {
        **result,
        "request_id": args.request_id,
        "software_revision": args.software_revision,
    }
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(
        ch for ch in args.request_id if ch.isalnum() or ch in "-_"
    )
    if not safe_request:
        raise SystemExit("REQUEST_ID_HAS_NO_SAFE_CHARACTERS")
    uploaded = store.upsert_json(
        name=f"TELEGRAM_MG_CANDIDATE_REPLAY__{safe_request}.json",
        obj=result,
    )
    print(json.dumps({"pass": True, "result": result, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
