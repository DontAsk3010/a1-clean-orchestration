from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from json import dumps
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_precision_study import (
    PRECISION_VARIANTS,
    _candidate_features,
    _same_day_outcome,
    _variant_matches,
)
from .telegram_mg_replay import evaluate_mg_packet


WINDOWS = (2, 3, 5, 10)
CONTEXT_MODES = (
    "ACTIVITY_WAKE",
    "ACTIVITY_RANGE_WAKE",
    "ACTIVITY_PATH_WAKE",
    "ACTIVITY_RANGE_PATH_WAKE",
)
BASE_VARIANT = "MG_P5_STEP050_RET025_150"


@dataclass(frozen=True)
class DayRecord:
    trading_date: str
    bars: tuple[dict[str, Any], ...]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _segment(bar: Mapping[str, Any]) -> str | None:
    if bool(bar.get("regular_session1")):
        return "S1"
    if bool(bar.get("regular_session2")):
        return "S2"
    return None


def _segment_prefix(bars: Sequence[Mapping[str, Any]], *, segment: str, count: int) -> list[Mapping[str, Any]] | None:
    if count < 1:
        return None
    rows = [row for row in bars if _segment(row) == segment]
    if len(rows) < count:
        return None
    return rows[:count]


def _prefix_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
    if not rows:
        return None
    closes = [_num(row.get("close")) for row in rows]
    highs = [_num(row.get("high")) for row in rows]
    lows = [_num(row.get("low")) for row in rows]
    values = [_num(row.get("trade_value")) for row in rows]
    if any(value is None for value in closes + highs + lows + values):
        return None
    close_values = [float(v) for v in closes if v is not None]
    high_values = [float(v) for v in highs if v is not None]
    low_values = [float(v) for v in lows if v is not None]
    activity_values = [float(v) for v in values if v is not None]
    if not close_values or close_values[0] <= 0 or close_values[-1] <= 0:
        return None
    current_close = close_values[-1]
    range_pct = (max(high_values) / min(low_values) - 1.0) * 100.0 if min(low_values) > 0 else None
    if range_pct is None:
        return None
    return {
        "activity_per_bar": sum(activity_values) / len(activity_values),
        "range_pct": range_pct,
        "path_pct": (current_close / close_values[0] - 1.0) * 100.0,
    }


def _current_segment_prefix(bars: Sequence[Mapping[str, Any]], index: int) -> tuple[str, list[Mapping[str, Any]]] | None:
    if index < 0 or index >= len(bars):
        return None
    segment = _segment(bars[index])
    if segment is None:
        return None
    prefix = [row for row in bars[: index + 1] if _segment(row) == segment]
    if not prefix:
        return None
    return segment, prefix


def _history_context(
    *,
    bars: Sequence[Mapping[str, Any]],
    index: int,
    history_by_date: Mapping[str, DayRecord],
    prior_dates: Sequence[str],
) -> dict[str, Any] | None:
    current = _current_segment_prefix(bars, index)
    if current is None:
        return None
    segment, current_rows = current
    current_stats = _prefix_stats(current_rows)
    if current_stats is None:
        return None

    prior_stats: list[dict[str, float]] = []
    for date in prior_dates:
        record = history_by_date.get(date)
        if record is None:
            return None
        prior_rows = _segment_prefix(record.bars, segment=segment, count=len(current_rows))
        if prior_rows is None:
            return None
        stats = _prefix_stats(prior_rows)
        if stats is None:
            return None
        prior_stats.append(stats)

    if not prior_stats:
        return None
    med_activity = float(median(row["activity_per_bar"] for row in prior_stats))
    med_range = float(median(row["range_pct"] for row in prior_stats))
    med_path = float(median(row["path_pct"] for row in prior_stats))
    activity_ratio = current_stats["activity_per_bar"] / med_activity if med_activity > 0 else None
    range_ratio = current_stats["range_pct"] / med_range if med_range > 0 else None
    path_delta = current_stats["path_pct"] - med_path
    if activity_ratio is None or range_ratio is None:
        return None

    return {
        "session_segment": segment,
        "comparable_bar_count": len(current_rows),
        "current_activity_per_bar": current_stats["activity_per_bar"],
        "prior_median_activity_per_bar": med_activity,
        "activity_ratio": activity_ratio,
        "current_range_pct": current_stats["range_pct"],
        "prior_median_range_pct": med_range,
        "range_ratio": range_ratio,
        "current_path_pct": current_stats["path_pct"],
        "prior_median_path_pct": med_path,
        "path_delta_pct": path_delta,
        "activity_wake": activity_ratio > 1.0,
        "range_wake": range_ratio > 1.0,
        "path_wake": path_delta > 0.0,
    }


def _mode_matches(context: Mapping[str, Any], mode: str) -> bool:
    a = bool(context.get("activity_wake"))
    r = bool(context.get("range_wake"))
    p = bool(context.get("path_wake"))
    if mode == "ACTIVITY_WAKE":
        return a
    if mode == "ACTIVITY_RANGE_WAKE":
        return a and r
    if mode == "ACTIVITY_PATH_WAKE":
        return a and p
    if mode == "ACTIVITY_RANGE_PATH_WAKE":
        return a and r and p
    raise ValueError(f"UNKNOWN_CONTEXT_MODE:{mode}")


def variant_name(window: int, mode: str) -> str:
    return f"MG_MD_W{int(window)}_{mode}"


def _blank() -> dict[str, float | int]:
    return {
        "signal_count": 0,
        "evaluable_count": 0,
        "tp1_or_better_count": 0,
        "tp2_count": 0,
        "no_tp_count": 0,
        "positive_close_count": 0,
        "sum_max_reward_pct": 0.0,
        "sum_max_drawdown_pct": 0.0,
        "sum_close_return_pct": 0.0,
    }


def _add(metric: dict[str, float | int], outcome: Mapping[str, Any]) -> None:
    metric["signal_count"] += 1
    if not outcome.get("evaluable"):
        return
    metric["evaluable_count"] += 1
    result = str(outcome.get("result"))
    metric["tp1_or_better_count"] += int(result in {"TP1_ONLY", "TP2"})
    metric["tp2_count"] += int(result == "TP2")
    metric["no_tp_count"] += int(result == "NO_TP")
    metric["positive_close_count"] += int(float(outcome.get("close_return_pct") or 0.0) > 0.0)
    metric["sum_max_reward_pct"] += float(outcome.get("max_reward_pct") or 0.0)
    metric["sum_max_drawdown_pct"] += float(outcome.get("max_drawdown_pct") or 0.0)
    metric["sum_close_return_pct"] += float(outcome.get("close_return_pct") or 0.0)


def _finalize(metric: Mapping[str, float | int]) -> dict[str, Any]:
    n = int(metric["evaluable_count"])
    return {
        "signal_count": int(metric["signal_count"]),
        "evaluable_count": n,
        "tp1_or_better_count": int(metric["tp1_or_better_count"]),
        "tp1_or_better_rate": float(metric["tp1_or_better_count"]) / n if n else None,
        "tp2_count": int(metric["tp2_count"]),
        "tp2_rate": float(metric["tp2_count"]) / n if n else None,
        "no_tp_count": int(metric["no_tp_count"]),
        "no_tp_rate": float(metric["no_tp_count"]) / n if n else None,
        "positive_close_rate": float(metric["positive_close_count"]) / n if n else None,
        "mean_max_reward_pct": float(metric["sum_max_reward_pct"]) / n if n else None,
        "mean_max_drawdown_pct": float(metric["sum_max_drawdown_pct"]) / n if n else None,
        "mean_close_return_pct": float(metric["sum_close_return_pct"]) / n if n else None,
    }


def build_multiday_study(*, source_names: Sequence[str], params: CandidateParams) -> dict[str, Any]:
    params.validate()
    if not source_names:
        raise ValueError("SOURCE_NAMES_REQUIRED")
    p5_rule = PRECISION_VARIANTS[BASE_VARIANT]
    lookback = max(params.effort_lookback, params.progress_lookback, params.high_lookback)
    max_window = max(WINDOWS)
    variant_ids = tuple(variant_name(window, mode) for window in WINDOWS for mode in CONTEXT_MODES)

    aggregate = {source: {variant: _blank() for variant in variant_ids} for source in source_names}
    daily: dict[str, dict[str, dict[str, dict[str, float | int]]]] = {
        source: defaultdict(lambda: {variant: _blank() for variant in variant_ids}) for source in source_names
    }
    samples: dict[str, dict[str, list[dict[str, Any]]]] = {
        source: {variant: [] for variant in variant_ids} for source in source_names
    }
    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_market_dates: list[str] = []
    current_market_date: str | None = None
    seen_market_dates: set[str] = set()
    source_packet_counts: dict[str, int] = {}
    source_row_counts: dict[str, int] = {}
    context_unavailable_counts: dict[str, dict[str, int]] = {
        source: {str(window): 0 for window in WINDOWS} for source in source_names
    }

    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        packet_count = 0
        row_count = 0

        for _manifest_row, packet in reader.iter_packets():
            date = str(packet.identity.trading_date)
            if current_market_date is None:
                current_market_date = date
            elif date != current_market_date:
                if current_market_date not in seen_market_dates:
                    completed_market_dates.append(current_market_date)
                    seen_market_dates.add(current_market_date)
                current_market_date = date
                keep_dates = set(completed_market_dates[-(max_window + 2):])
                for ticker in list(history):
                    history[ticker] = {d: rec for d, rec in history[ticker].items() if d in keep_dates}
                    if not history[ticker]:
                        del history[ticker]

            all_bars, _mapping = packet_to_formula_bars(packet)
            bars = [bar for bar in all_bars if bar["session_eligible"]]
            packet_count += 1
            row_count += len(all_bars)
            ticker = str(packet.identity.ticker)
            ticker_history = history.get(ticker, {})

            if bars:
                mg_rows = evaluate_mg_packet(bars, params)
                first_by_variant: dict[str, tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]] = {}

                for i, mg in enumerate(mg_rows):
                    if not mg.get("publication_slot"):
                        continue
                    if mg["variants"].get("MG_B_PATH_VALUE") != TRUE:
                        continue
                    p5_features = _candidate_features(bars, i, lookback=lookback)
                    if not _variant_matches(p5_features, p5_rule):
                        continue
                    entry = _num(bars[i].get("close"))
                    tp1 = _num(mg["targets"].get("tp1"))
                    tp2 = _num(mg["targets"].get("tp2"))
                    if entry is None or entry <= 0 or tp1 is None or tp2 is None:
                        continue
                    outcome = _same_day_outcome(bars, i, entry=entry, tp1=tp1, tp2=tp2)

                    for window in WINDOWS:
                        if len(completed_market_dates) < window:
                            context_unavailable_counts[source_name][str(window)] += 1
                            continue
                        prior_dates = completed_market_dates[-window:]
                        context = _history_context(
                            bars=bars,
                            index=i,
                            history_by_date=ticker_history,
                            prior_dates=prior_dates,
                        )
                        if context is None:
                            context_unavailable_counts[source_name][str(window)] += 1
                            continue
                        for mode in CONTEXT_MODES:
                            variant = variant_name(window, mode)
                            if variant in first_by_variant:
                                continue
                            if _mode_matches(context, mode):
                                first_by_variant[variant] = (i, outcome, context, p5_features)

                for variant, (i, outcome, context, p5_features) in first_by_variant.items():
                    _add(aggregate[source_name][variant], outcome)
                    _add(daily[source_name][date][variant], outcome)
                    if len(samples[source_name][variant]) < 12:
                        samples[source_name][variant].append(
                            {
                                "trading_date": date,
                                "ticker": ticker,
                                "timestamp": bars[i].get("timestamp"),
                                "entry": _num(bars[i].get("close")),
                                "tp1": _num(mg_rows[i]["targets"].get("tp1")),
                                "tp2": _num(mg_rows[i]["targets"].get("tp2")),
                                "context": context,
                                "p5_features": p5_features,
                                "outcome": outcome,
                            }
                        )

                history.setdefault(ticker, {})[date] = DayRecord(
                    trading_date=date,
                    bars=tuple(dict(bar) for bar in bars),
                )

        source_packet_counts[source_name] = packet_count
        source_row_counts[source_name] = row_count

    aggregate_final = {
        source: {variant: _finalize(raw) for variant, raw in variants.items()}
        for source, variants in aggregate.items()
    }
    daily_final = {
        source: {
            date: {variant: _finalize(raw) for variant, raw in variants.items()}
            for date, variants in sorted(dates.items())
        }
        for source, dates in daily.items()
    }

    stability: dict[str, Any] = {}
    for variant in variant_ids:
        period_rows = [aggregate_final[source][variant] for source in source_names]
        evaluable_periods = [row for row in period_rows if int(row["evaluable_count"]) > 0]
        rates = [float(row["tp1_or_better_rate"]) for row in evaluable_periods if row["tp1_or_better_rate"] is not None]
        tp2_rates = [float(row["tp2_rate"]) for row in evaluable_periods if row["tp2_rate"] is not None]
        no_tp_rates = [float(row["no_tp_rate"]) for row in evaluable_periods if row["no_tp_rate"] is not None]
        stability[variant] = {
            "period_count": len(evaluable_periods),
            "min_tp1_or_better_rate": min(rates) if rates else None,
            "median_tp1_or_better_rate": float(median(rates)) if rates else None,
            "min_tp2_rate": min(tp2_rates) if tp2_rates else None,
            "median_tp2_rate": float(median(tp2_rates)) if tp2_rates else None,
            "max_no_tp_rate": max(no_tp_rates) if no_tp_rates else None,
            "total_evaluable": sum(int(row["evaluable_count"]) for row in evaluable_periods),
            "total_signals": sum(int(row["signal_count"]) for row in period_rows),
        }

    return {
        "schema": "A1_TELEGRAM_MG_MULTIDAY_CONTEXT_STUDY_V1",
        "status": "RESEARCH_CANDIDATE_NOT_FINAL",
        "purpose": "EARLY_POTENTIAL_NEW_MOTION_WITH_PRIOR_STATE_CONTEXT_AND_SAME_DAY_REWARD",
        "base_intraday_gate": BASE_VARIANT,
        "windows_prior_trading_days": list(WINDOWS),
        "context_modes": list(CONTEXT_MODES),
        "context_comparison": "SAME_TICKER_SAME_SESSION_SEGMENT_SAME_OBSERVED_BAR_COUNT_VS_MEDIAN_OF_EXACT_PRIOR_MARKET_DATES",
        "source_names": list(source_names),
        "source_packet_counts": source_packet_counts,
        "source_row_counts": source_row_counts,
        "aggregate": aggregate_final,
        "daily": daily_final,
        "cross_period_stability": stability,
        "context_unavailable_counts": context_unavailable_counts,
        "samples": samples,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_evaluation_only": True,
        "same_alert_bar_high_counted_for_reward": False,
        "h_plus_1_used_to_qualify_mg": False,
        "notes": [
            "The 2/3/5/10-day windows are candidate baseline horizons, not canonical fixed horizons.",
            "Exact prior market dates are required per ticker; missing prior ticker-day context makes that window unavailable.",
            "Activity/range/path wake comparisons are relative to the ticker's own prior-state median at a comparable session stage.",
            "This study does not promote any variant to canonical MG and does not modify Telegram output contracts.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-multiday-context-study")
    parser.add_argument("--source-name", action="append", required=True)
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
    report = build_multiday_study(source_names=args.source_name, params=params)
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_MULTIDAY_CONTEXT_STUDY__{safe_request}.json", obj=report)
    print(dumps({"pass": True, "drive_artifact": uploaded, "summary": report["cross_period_stability"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
