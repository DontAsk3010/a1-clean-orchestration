from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_replay import evaluate_mg_packet


# Fixed rounded development candidates.  These are research dimensions only,
# not accepted/final thresholds.  January validation must use one frozen
# variant selected from December; it may not re-select or retune this grid.
PRECISION_VARIANTS: dict[str, dict[str, float | None]] = {
    "MG_P0_SESSION_SAFE_BASE": {
        "max_local_range_step_pct": None,
        "min_recent_return_pct": None,
        "max_recent_return_pct": None,
    },
    "MG_P1_STEP075_RET025_200": {
        "max_local_range_step_pct": 0.75,
        "min_recent_return_pct": 0.25,
        "max_recent_return_pct": 2.00,
    },
    "MG_P2_STEP060_RET025_200": {
        "max_local_range_step_pct": 0.60,
        "min_recent_return_pct": 0.25,
        "max_recent_return_pct": 2.00,
    },
    "MG_P3_STEP075_RET025_150": {
        "max_local_range_step_pct": 0.75,
        "min_recent_return_pct": 0.25,
        "max_recent_return_pct": 1.50,
    },
    "MG_P4_STEP075_RET050_150": {
        "max_local_range_step_pct": 0.75,
        "min_recent_return_pct": 0.50,
        "max_recent_return_pct": 1.50,
    },
    "MG_P5_STEP050_RET025_150": {
        "max_local_range_step_pct": 0.50,
        "min_recent_return_pct": 0.25,
        "max_recent_return_pct": 1.50,
    },
}


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


def _candidate_features(
    bars: Sequence[Mapping[str, Any]], index: int, *, lookback: int
) -> dict[str, Any]:
    """Derive causal, session-safe refinement features at one alert bar."""
    if lookback < 2 or index < lookback:
        return {
            "session_safe": False,
            "session_segment": _segment(bars[index]) if 0 <= index < len(bars) else None,
            "recent_return_pct": None,
            "local_range_step_pct": None,
            "recent_non_down_ratio": None,
        }

    segment = _segment(bars[index])
    # Existing MG_B needs prior-lookback values plus current bar.  Requiring
    # all lookback+1 observations to be in the same session prevents S1->S2
    # lunch-gap contamination in path/value comparisons.
    dependency = bars[index - lookback : index + 1]
    if segment is None or any(_segment(row) != segment for row in dependency):
        return {
            "session_safe": False,
            "session_segment": segment,
            "recent_return_pct": None,
            "local_range_step_pct": None,
            "recent_non_down_ratio": None,
        }

    window = bars[index - lookback + 1 : index + 1]
    closes = [_num(row.get("close")) for row in window]
    highs = [_num(row.get("high")) for row in window]
    lows = [_num(row.get("low")) for row in window]
    if any(value is None for value in closes + highs + lows):
        return {
            "session_safe": True,
            "session_segment": segment,
            "recent_return_pct": None,
            "local_range_step_pct": None,
            "recent_non_down_ratio": None,
        }

    close_values = [float(v) for v in closes if v is not None]
    high_values = [float(v) for v in highs if v is not None]
    low_values = [float(v) for v in lows if v is not None]
    current_close = close_values[-1]
    if current_close <= 0 or close_values[0] <= 0:
        recent_return_pct = None
        local_step_pct = None
    else:
        recent_return_pct = (current_close / close_values[0] - 1.0) * 100.0
        positive_ranges = [
            high - low for high, low in zip(high_values, low_values, strict=True) if high > low
        ]
        local_step_pct = (
            (float(median(positive_ranges)) / current_close) * 100.0
            if positive_ranges
            else None
        )

    non_down_steps = sum(
        close_values[j] >= close_values[j - 1] for j in range(1, len(close_values))
    )
    non_down_ratio = non_down_steps / (len(close_values) - 1)
    return {
        "session_safe": True,
        "session_segment": segment,
        "recent_return_pct": recent_return_pct,
        "local_range_step_pct": local_step_pct,
        "recent_non_down_ratio": non_down_ratio,
    }


def _variant_matches(features: Mapping[str, Any], rule: Mapping[str, float | None]) -> bool:
    if not bool(features.get("session_safe")):
        return False
    step = _num(features.get("local_range_step_pct"))
    ret = _num(features.get("recent_return_pct"))
    max_step = _num(rule.get("max_local_range_step_pct"))
    min_ret = _num(rule.get("min_recent_return_pct"))
    max_ret = _num(rule.get("max_recent_return_pct"))
    if max_step is not None and (step is None or step > max_step):
        return False
    if min_ret is not None and (ret is None or ret < min_ret):
        return False
    if max_ret is not None and (ret is None or ret > max_ret):
        return False
    return True


def _same_day_outcome(
    bars: Sequence[Mapping[str, Any]], index: int, *, entry: float, tp1: float, tp2: float
) -> dict[str, Any]:
    # Current alert bar is intentionally excluded: only reward available after
    # publication may count toward same-day signal performance.
    future = bars[index + 1 :]
    if not future:
        return {
            "evaluable": False,
            "result": "NO_FUTURE_BAR",
            "tp1_hit": False,
            "tp2_hit": False,
            "max_reward_pct": None,
            "max_drawdown_pct": None,
            "close_return_pct": None,
        }
    highs = [_num(row.get("high")) for row in future]
    lows = [_num(row.get("low")) for row in future]
    closes = [_num(row.get("close")) for row in future]
    if not any(v is not None for v in highs) or not any(v is not None for v in lows):
        return {
            "evaluable": False,
            "result": "NO_FUTURE_BAR",
            "tp1_hit": False,
            "tp2_hit": False,
            "max_reward_pct": None,
            "max_drawdown_pct": None,
            "close_return_pct": None,
        }
    high_values = [float(v) for v in highs if v is not None]
    low_values = [float(v) for v in lows if v is not None]
    close_values = [float(v) for v in closes if v is not None]
    max_high = max(high_values)
    min_low = min(low_values)
    final_close = close_values[-1] if close_values else entry
    tp1_hit = max_high >= tp1
    tp2_hit = max_high >= tp2
    return {
        "evaluable": True,
        "result": "TP2" if tp2_hit else ("TP1_ONLY" if tp1_hit else "NO_TP"),
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "max_reward_pct": (max_high / entry - 1.0) * 100.0,
        "max_drawdown_pct": (min_low / entry - 1.0) * 100.0,
        "close_return_pct": (final_close / entry - 1.0) * 100.0,
    }


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


def build_precision_study(
    *,
    source_name: str,
    params: CandidateParams,
    mode: str,
    selected_variant: str | None,
) -> dict[str, Any]:
    params.validate()
    if mode not in {"DEVELOPMENT_COMPARE_ALL", "FROZEN_VALIDATION_ONE"}:
        raise ValueError(f"UNSUPPORTED_MODE:{mode}")
    if mode == "FROZEN_VALIDATION_ONE":
        if not selected_variant or selected_variant not in PRECISION_VARIANTS:
            raise ValueError("VALIDATION_SELECTED_VARIANT_REQUIRED")
        active_variants = (selected_variant,)
    else:
        if selected_variant:
            raise ValueError("DEVELOPMENT_MUST_NOT_PRESELECT_VARIANT")
        active_variants = tuple(PRECISION_VARIANTS)

    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    lookback = max(params.effort_lookback, params.progress_lookback, params.high_lookback)

    aggregate = {name: _blank() for name in active_variants}
    daily: dict[str, dict[str, dict[str, float | int]]] = defaultdict(
        lambda: {name: _blank() for name in active_variants}
    )
    baseline_original = _blank()
    baseline_session_safe = _blank()
    packet_count = 0
    eligible_row_count = 0
    original_first_alert_count = 0
    session_safe_first_alert_count = 0
    first_alert_samples: dict[str, list[dict[str, Any]]] = {name: [] for name in active_variants}

    for _manifest_row, packet in reader.iter_packets():
        all_bars, _mapping = packet_to_formula_bars(packet)
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        if not bars:
            continue
        packet_count += 1
        eligible_row_count += len(bars)
        mg_rows = evaluate_mg_packet(bars, params)

        original_first: tuple[int, dict[str, Any]] | None = None
        first_by_variant: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
        first_session_safe: tuple[int, dict[str, Any], dict[str, Any]] | None = None

        for i, mg in enumerate(mg_rows):
            if not mg.get("publication_slot"):
                continue
            if mg["variants"].get("MG_B_PATH_VALUE") != TRUE:
                continue
            tp1 = _num(mg["targets"].get("tp1"))
            tp2 = _num(mg["targets"].get("tp2"))
            entry = _num(bars[i].get("close"))
            if entry is None or entry <= 0 or tp1 is None or tp2 is None:
                continue
            outcome = _same_day_outcome(bars, i, entry=entry, tp1=tp1, tp2=tp2)
            if original_first is None:
                original_first = (i, outcome)

            features = _candidate_features(bars, i, lookback=lookback)
            if features["session_safe"] and first_session_safe is None:
                first_session_safe = (i, outcome, features)

            for variant in active_variants:
                if variant in first_by_variant:
                    continue
                if _variant_matches(features, PRECISION_VARIANTS[variant]):
                    first_by_variant[variant] = (i, outcome, features)

        if original_first is not None:
            original_first_alert_count += 1
            _add(baseline_original, original_first[1])
        if first_session_safe is not None:
            session_safe_first_alert_count += 1
            _add(baseline_session_safe, first_session_safe[1])

        date = str(packet.identity.trading_date)
        for variant, (i, outcome, features) in first_by_variant.items():
            _add(aggregate[variant], outcome)
            _add(daily[date][variant], outcome)
            if len(first_alert_samples[variant]) < 40:
                first_alert_samples[variant].append(
                    {
                        "trading_date": date,
                        "ticker": str(packet.identity.ticker),
                        "timestamp": bars[i].get("timestamp"),
                        "entry": _num(bars[i].get("close")),
                        "tp1": _num(mg_rows[i]["targets"].get("tp1")),
                        "tp2": _num(mg_rows[i]["targets"].get("tp2")),
                        "features": features,
                        "outcome": outcome,
                    }
                )

    daily_final: dict[str, Any] = {}
    for date in sorted(daily):
        daily_final[date] = {name: _finalize(daily[date][name]) for name in active_variants}

    date_signal_stats: dict[str, Any] = {}
    for variant in active_variants:
        counts = [int(daily[date][variant]["signal_count"]) for date in sorted(daily)]
        date_signal_stats[variant] = {
            "trading_dates_observed": len(counts),
            "zero_signal_dates": sum(1 for value in counts if value == 0),
            "mean_first_signals_per_date": (sum(counts) / len(counts)) if counts else None,
            "max_first_signals_on_one_date": max(counts) if counts else None,
        }

    return {
        "schema": "A1_TELEGRAM_MG_SAME_DAY_PRECISION_STUDY_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "source_name": source_name,
        "source_identity": reader.identity.as_dict(),
        "mode": mode,
        "selected_variant": selected_variant,
        "base_variant": "MG_B_PATH_VALUE",
        "objective": "FEWER_CLEANER_FIRST_ALERTS_WITH_SAME_TRADING_DAY_REWARD",
        "primary_metric": "FIRST_ALERT_TP1_OR_BETTER_THROUGH_SAME_DAY_CLOSE",
        "secondary_metrics": ["TP2_RATE", "NO_TP_RATE", "MEAN_MAX_DRAWDOWN", "SIGNALS_PER_DATE"],
        "selection_rule": "DEVELOPMENT_ON_DECEMBER_ONLY_THEN_FREEZE_ONE_VARIANT_BEFORE_JANUARY_VALIDATION",
        "params": params.__dict__,
        "precision_variant_rules": {name: PRECISION_VARIANTS[name] for name in active_variants},
        "packet_count": packet_count,
        "eligible_row_count": eligible_row_count,
        "original_mg_b_first_alert_count": original_first_alert_count,
        "session_safe_mg_b_first_alert_count": session_safe_first_alert_count,
        "baseline_original_mg_b": _finalize(baseline_original),
        "baseline_session_safe_mg_b": _finalize(baseline_session_safe),
        "variant_summary": {name: _finalize(aggregate[name]) for name in active_variants},
        "date_signal_stats": date_signal_stats,
        "daily_summary": daily_final,
        "first_alert_samples": first_alert_samples,
        "same_bar_high_counted": False,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_evaluation_only": True,
        "h1_used_for_mg_selection": False,
        "final_or_canonical_claim": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-precision-study")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--selected-variant", default="")
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
    result = build_precision_study(
        source_name=args.source_name,
        params=params,
        mode=args.mode,
        selected_variant=(args.selected_variant or None),
    )
    result = {**result, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(
        name=f"TELEGRAM_MG_PRECISION_STUDY__{safe_request}.json",
        obj=result,
    )
    print(json.dumps({"pass": True, "result": result, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
