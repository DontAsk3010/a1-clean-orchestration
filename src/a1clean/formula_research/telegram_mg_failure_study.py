from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import fmean, median
from typing import Any

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams
from .telegram_mg_replay import _num, evaluate_mg_packet
from .telegram_mg_reward_audit import build_reward_audit


def _segment(bar: dict[str, Any]) -> str | None:
    if bar.get("regular_session1"):
        return "S1"
    if bar.get("regular_session2"):
        return "S2"
    return None


def _same_segment_indices(bars: list[dict[str, Any]], index: int) -> list[int]:
    seg = _segment(bars[index])
    if seg is None:
        return []
    out: list[int] = []
    for j in range(index, -1, -1):
        if _segment(bars[j]) != seg:
            break
        out.append(j)
    return list(reversed(out))


def _mean(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _features(
    bars: list[dict[str, Any]], mg_rows: list[dict[str, Any]], index: int, lookback: int
) -> dict[str, Any]:
    row = bars[index]
    close = _num(row.get("close"))
    high = _num(row.get("high"))
    low = _num(row.get("low"))
    value = _num(row.get("trade_value"))
    seg = _segment(row)
    seg_idx = _same_segment_indices(bars, index)
    prior_idx = seg_idx[:-1][-lookback:]
    current_idx = seg_idx[-lookback:]

    prior_closes = [_num(bars[j].get("close")) for j in prior_idx]
    prior_values = [_num(bars[j].get("trade_value")) for j in prior_idx]
    current_closes = [_num(bars[j].get("close")) for j in current_idx]
    valid_prior_closes = [float(v) for v in prior_closes if v is not None]
    valid_prior_values = [float(v) for v in prior_values if v is not None]
    valid_current_closes = [float(v) for v in current_closes if v is not None]

    value_ratio = None
    if value is not None and len(valid_prior_values) == lookback:
        base = _mean(valid_prior_values)
        if base not in (None, 0.0):
            value_ratio = float(value) / float(base)

    recent_return_pct = None
    if close is not None and len(valid_prior_closes) == lookback and valid_prior_closes[0] != 0:
        recent_return_pct = (float(close) / valid_prior_closes[0] - 1.0) * 100.0

    non_down_ratio = None
    if len(valid_current_closes) == lookback and lookback > 1:
        steps = [
            valid_current_closes[j] >= valid_current_closes[j - 1]
            for j in range(1, len(valid_current_closes))
        ]
        non_down_ratio = sum(steps) / len(steps)

    acceptance_position = None
    if None not in (close, high, low) and float(high) > float(low):
        acceptance_position = (float(close) - float(low)) / (float(high) - float(low))

    seg_high = None
    seg_low = None
    if seg_idx:
        highs = [_num(bars[j].get("high")) for j in seg_idx]
        lows = [_num(bars[j].get("low")) for j in seg_idx]
        hv = [float(v) for v in highs if v is not None]
        lv = [float(v) for v in lows if v is not None]
        seg_high = max(hv) if hv else None
        seg_low = min(lv) if lv else None

    below_segment_high_pct = None
    if close not in (None, 0.0) and seg_high is not None:
        below_segment_high_pct = (float(seg_high) / float(close) - 1.0) * 100.0

    segment_range_position = None
    if close is not None and seg_high is not None and seg_low is not None and seg_high > seg_low:
        segment_range_position = (float(close) - seg_low) / (seg_high - seg_low)

    target = mg_rows[index]["targets"]
    tp1 = _num(target.get("tp1"))
    tp2 = _num(target.get("tp2"))
    step = _num(target.get("local_range_step"))
    tp1_distance_pct = None if close in (None, 0.0) or tp1 is None else (tp1 / float(close) - 1.0) * 100.0
    tp2_distance_pct = None if close in (None, 0.0) or tp2 is None else (tp2 / float(close) - 1.0) * 100.0
    local_step_pct = None if close in (None, 0.0) or step is None else (step / float(close)) * 100.0

    # Detect the known session-boundary contamination in the original MG_B logic:
    # a causal lookback is allowed to use prior bars from another regular-session segment.
    original_start = index - lookback
    original_window_segments = []
    if original_start >= 0:
        original_window_segments = [_segment(bars[j]) for j in range(original_start, index + 1)]
    crosses_session_segment = bool(
        original_window_segments
        and seg is not None
        and any(item != seg for item in original_window_segments)
    )

    return {
        "session_segment": seg,
        "bars_since_segment_start": len(seg_idx) - 1 if seg_idx else None,
        "crosses_session_segment_in_original_lookback": crosses_session_segment,
        "value_ratio_vs_prior_segment_bars": value_ratio,
        "recent_return_pct": recent_return_pct,
        "recent_non_down_ratio": non_down_ratio,
        "bar_acceptance_position": acceptance_position,
        "below_segment_high_pct": below_segment_high_pct,
        "segment_range_position": segment_range_position,
        "tp1_distance_pct": tp1_distance_pct,
        "tp2_distance_pct": tp2_distance_pct,
        "local_range_step_pct": local_step_pct,
        "components": mg_rows[index]["components"],
    }


def _whole_day_outcome(
    bars: list[dict[str, Any]] | None, *, entry: float, tp1: float, tp2: float
) -> dict[str, Any]:
    if not bars:
        return {
            "available": False,
            "tp1_hit": False,
            "tp2_hit": False,
            "max_reward_pct": None,
            "max_drawdown_pct": None,
            "close_return_pct": None,
            "open_gap_pct": None,
        }
    highs = [float(v) for v in (_num(r.get("high")) for r in bars) if v is not None]
    lows = [float(v) for v in (_num(r.get("low")) for r in bars) if v is not None]
    closes = [float(v) for v in (_num(r.get("close")) for r in bars) if v is not None]
    opens = [float(v) for v in (_num(r.get("open")) for r in bars) if v is not None]
    max_high = max(highs) if highs else None
    min_low = min(lows) if lows else None
    close_price = closes[-1] if closes else None
    open_price = opens[0] if opens else None
    return {
        "available": True,
        "tp1_hit": bool(max_high is not None and max_high >= tp1),
        "tp2_hit": bool(max_high is not None and max_high >= tp2),
        "max_reward_pct": None if max_high is None else (max_high / entry - 1.0) * 100.0,
        "max_drawdown_pct": None if min_low is None else (min_low / entry - 1.0) * 100.0,
        "close_return_pct": None if close_price is None else (close_price / entry - 1.0) * 100.0,
        "open_gap_pct": None if open_price is None else (open_price / entry - 1.0) * 100.0,
    }


def _numeric_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = [float(row[field]) for row in rows if row.get(field) is not None and math.isfinite(float(row[field]))]
    if not values:
        return {"count": 0, "mean": None, "median": None}
    return {"count": len(values), "mean": fmean(values), "median": median(values)}


def build_failure_study(
    *, source_name: str, trading_date: str, variant: str, params: CandidateParams
) -> dict[str, Any]:
    reward = build_reward_audit(
        source_name=source_name,
        trading_date=trading_date,
        variant=variant,
        params=params,
    )

    api = build_drive_api(read_write=False)
    reader_dates = GovernedSourceReader(api, source_name=source_name)
    trading_dates: set[str] = set()
    for _manifest_row, packet in reader_dates.iter_packets():
        trading_dates.add(str(packet.identity.trading_date))
    ordered_dates = sorted(trading_dates)
    if trading_date not in ordered_dates:
        raise ValueError(f"TRADING_DATE_NOT_IN_SOURCE:{trading_date}")
    pos = ordered_dates.index(trading_date)
    next_date = ordered_dates[pos + 1] if pos + 1 < len(ordered_dates) else None

    target_bars: dict[str, list[dict[str, Any]]] = {}
    h1_bars: dict[str, list[dict[str, Any]]] = {}
    reader = GovernedSourceReader(api, source_name=source_name)
    for _manifest_row, packet in reader.iter_packets():
        date = str(packet.identity.trading_date)
        if date not in {trading_date, next_date}:
            continue
        all_bars, _mapping = packet_to_formula_bars(packet)
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        if not bars:
            continue
        ticker = str(packet.identity.ticker)
        if date == trading_date:
            target_bars[ticker] = bars
        elif next_date is not None and date == next_date:
            h1_bars[ticker] = bars

    studied: list[dict[str, Any]] = []
    class_counts: Counter[str] = Counter()
    for alert in reward["first_appearance_per_ticker"]:
        ticker = str(alert["CODE"])
        bars = target_bars.get(ticker)
        if not bars:
            continue
        index_map = {str(row.get("timestamp")): i for i, row in enumerate(bars)}
        idx = index_map.get(str(alert["as_of"]))
        if idx is None:
            continue
        mg_rows = evaluate_mg_packet(bars, params)
        features = _features(bars, mg_rows, idx, max(params.effort_lookback, params.progress_lookback))
        h1 = _whole_day_outcome(
            h1_bars.get(ticker),
            entry=float(alert["PRICE"]),
            tp1=float(alert["TP-1"]),
            tp2=float(alert["TP-2"]),
        )
        same_day = str(alert["result"])
        if same_day == "TP2":
            cls = "SAME_DAY_TP2"
        elif same_day == "TP1_ONLY":
            cls = "SAME_DAY_TP1_ONLY"
        elif same_day == "NO_FUTURE_BAR":
            cls = "SAME_DAY_NOT_EVALUABLE"
        elif h1["available"] and h1["tp2_hit"]:
            cls = "DEFERRED_H1_TP2"
        elif h1["available"] and h1["tp1_hit"]:
            cls = "DEFERRED_H1_TP1_ONLY"
        elif h1["available"] and (h1["max_reward_pct"] or 0.0) > 0.0:
            cls = "DEFERRED_H1_POSITIVE_SUB_TP"
        elif h1["available"]:
            cls = "PERSISTENT_FAIL_THROUGH_H1"
        else:
            cls = "H1_UNAVAILABLE"
        class_counts[cls] += 1
        studied.append(
            {
                **alert,
                "failure_continuation_class": cls,
                "features_at_alert": features,
                "h1_trading_date": next_date,
                "h1_outcome_against_original_alert": h1,
            }
        )

    no_tp = [row for row in studied if row.get("result") == "NO_TP"]
    no_tp_counts = Counter(row["failure_continuation_class"] for row in no_tp)
    cross_segment_no_tp = sum(
        1 for row in no_tp if row["features_at_alert"].get("crosses_session_segment_in_original_lookback")
    )
    cross_segment_all = sum(
        1 for row in studied if row["features_at_alert"].get("crosses_session_segment_in_original_lookback")
    )

    flat_rows: list[dict[str, Any]] = []
    for row in studied:
        f = row["features_at_alert"]
        flat_rows.append(
            {
                "class": row["failure_continuation_class"],
                "same_day_result": row["result"],
                "CHG%": row.get("CHG%"),
                "same_day_max_reward_pct": row.get("max_reward_pct"),
                "same_day_max_drawdown_pct": row.get("max_drawdown_pct"),
                "same_day_close_return_pct": row.get("close_return_pct"),
                "value_ratio": f.get("value_ratio_vs_prior_segment_bars"),
                "recent_return_pct": f.get("recent_return_pct"),
                "recent_non_down_ratio": f.get("recent_non_down_ratio"),
                "bar_acceptance_position": f.get("bar_acceptance_position"),
                "below_segment_high_pct": f.get("below_segment_high_pct"),
                "segment_range_position": f.get("segment_range_position"),
                "tp1_distance_pct": f.get("tp1_distance_pct"),
                "tp2_distance_pct": f.get("tp2_distance_pct"),
                "local_range_step_pct": f.get("local_range_step_pct"),
            }
        )

    fields = [
        "CHG%", "same_day_max_reward_pct", "same_day_max_drawdown_pct",
        "same_day_close_return_pct", "value_ratio", "recent_return_pct",
        "recent_non_down_ratio", "bar_acceptance_position", "below_segment_high_pct",
        "segment_range_position", "tp1_distance_pct", "tp2_distance_pct",
        "local_range_step_pct",
    ]
    feature_summary: dict[str, Any] = {}
    for cls in sorted(class_counts):
        cls_rows = [row for row in flat_rows if row["class"] == cls]
        feature_summary[cls] = {field: _numeric_summary(cls_rows, field) for field in fields}

    return {
        "schema": "A1_TELEGRAM_MG_FAILURE_CONTINUATION_STUDY_V1",
        "status": "RESEARCH_DIAGNOSTIC_NOT_CANONICAL",
        "source_name": source_name,
        "trading_date": trading_date,
        "next_governed_trading_date": next_date,
        "variant": variant,
        "params": params.__dict__,
        "first_appearance_count": len(studied),
        "same_day_and_h1_class_counts": dict(class_counts),
        "same_day_no_tp_count": len(no_tp),
        "same_day_no_tp_h1_breakdown": dict(no_tp_counts),
        "original_lookback_crossed_session_segment_count_all": cross_segment_all,
        "original_lookback_crossed_session_segment_count_no_tp": cross_segment_no_tp,
        "feature_summary_by_outcome_class": feature_summary,
        "studied_first_appearances": studied,
        "formula_state_future_leakage": False,
        "h1_used_for_evaluation_only": True,
        "same_bar_high_counted_for_same_day_reward": False,
        "final_or_canonical_claim": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-failure-study")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
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
    result = build_failure_study(
        source_name=args.source_name,
        trading_date=args.trading_date,
        variant=args.variant,
        params=params,
    )
    result = {**result, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(
        name=f"TELEGRAM_MG_FAILURE_STUDY__{safe_request}.json",
        obj=result,
    )
    print(json.dumps({"pass": True, "result": result, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
