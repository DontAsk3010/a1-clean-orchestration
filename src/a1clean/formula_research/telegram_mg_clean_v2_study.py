from __future__ import annotations

import argparse
from collections import defaultdict
from json import dumps
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_multiday_context_study import (
    DayRecord,
    _add,
    _blank,
    _finalize,
    _history_context,
    _num,
)
from .telegram_mg_precision_study import (
    PRECISION_VARIANTS,
    _candidate_features,
    _same_day_outcome,
    _variant_matches,
)
from .telegram_mg_replay import evaluate_mg_packet


BASE_VARIANT = "MG_P5_STEP050_RET025_150"
PRIOR_WINDOW = 2

# Transparent research profiles. These are development candidates, not accepted
# thresholds. Each profile adds explicit strength/freshness conditions to the
# same causal P5 + two-day prior-state comparison; there is no weighted score.
CLEAN_PROFILES: dict[str, dict[str, float | None]] = {
    "ARP_BASE": {
        "min_activity_ratio": 1.00,
        "min_range_ratio": 1.00,
        "min_path_delta_pct": 0.00,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": None,
        "max_day_change_pct": None,
    },
    "ARP_BASE_FRESH3_D5": {
        "min_activity_ratio": 1.00,
        "min_range_ratio": 1.00,
        "min_path_delta_pct": 0.00,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": 3.00,
        "max_day_change_pct": 5.00,
    },
    "ARP_BASE_FRESH2_D3": {
        "min_activity_ratio": 1.00,
        "min_range_ratio": 1.00,
        "min_path_delta_pct": 0.00,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": 2.00,
        "max_day_change_pct": 3.00,
    },
    "ARP_MOD": {
        "min_activity_ratio": 1.25,
        "min_range_ratio": 1.10,
        "min_path_delta_pct": 0.10,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": None,
        "max_day_change_pct": None,
    },
    "ARP_MOD_FRESH3_D5": {
        "min_activity_ratio": 1.25,
        "min_range_ratio": 1.10,
        "min_path_delta_pct": 0.10,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": 3.00,
        "max_day_change_pct": 5.00,
    },
    "ARP_MOD_FRESH2_D3": {
        "min_activity_ratio": 1.25,
        "min_range_ratio": 1.10,
        "min_path_delta_pct": 0.10,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": 2.00,
        "max_day_change_pct": 3.00,
    },
    "ARP_STRONG": {
        "min_activity_ratio": 1.50,
        "min_range_ratio": 1.20,
        "min_path_delta_pct": 0.20,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": None,
        "max_day_change_pct": None,
    },
    "ARP_STRONG_FRESH3_D5": {
        "min_activity_ratio": 1.50,
        "min_range_ratio": 1.20,
        "min_path_delta_pct": 0.20,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": 3.00,
        "max_day_change_pct": 5.00,
    },
    "ARP_STRONG_FRESH2_D3": {
        "min_activity_ratio": 1.50,
        "min_range_ratio": 1.20,
        "min_path_delta_pct": 0.20,
        "min_current_path_pct": 0.00,
        "max_current_path_pct": 2.00,
        "max_day_change_pct": 3.00,
    },
}


def variant_name(profile: str) -> str:
    return f"MG_CLEAN_W2_{profile}"


def _enrich_context(
    context: Mapping[str, Any],
    *,
    bars: Sequence[Mapping[str, Any]],
    index: int,
    ticker_history: Mapping[str, DayRecord],
    prior_dates: Sequence[str],
) -> dict[str, Any] | None:
    if not prior_dates:
        return None
    previous = ticker_history.get(prior_dates[-1])
    if previous is None or not previous.bars:
        return None
    current_close = _num(bars[index].get("close"))
    previous_close = _num(previous.bars[-1].get("close"))
    if current_close is None or current_close <= 0 or previous_close is None or previous_close <= 0:
        return None
    return {
        **dict(context),
        "previous_regular_close": previous_close,
        "day_change_pct": (current_close / previous_close - 1.0) * 100.0,
    }


def _profile_matches(context: Mapping[str, Any], profile: Mapping[str, float | None]) -> bool:
    activity = _num(context.get("activity_ratio"))
    range_ratio = _num(context.get("range_ratio"))
    path_delta = _num(context.get("path_delta_pct"))
    current_path = _num(context.get("current_path_pct"))
    day_change = _num(context.get("day_change_pct"))
    if None in (activity, range_ratio, path_delta, current_path, day_change):
        return False

    assert activity is not None
    assert range_ratio is not None
    assert path_delta is not None
    assert current_path is not None
    assert day_change is not None

    if activity <= float(profile["min_activity_ratio"] or 0.0):
        return False
    if range_ratio <= float(profile["min_range_ratio"] or 0.0):
        return False
    if path_delta <= float(profile["min_path_delta_pct"] or 0.0):
        return False
    if current_path <= float(profile["min_current_path_pct"] or 0.0):
        return False

    max_current = profile.get("max_current_path_pct")
    if max_current is not None and current_path > float(max_current):
        return False
    max_day = profile.get("max_day_change_pct")
    if max_day is not None and day_change > float(max_day):
        return False
    return True


def build_clean_v2_study(
    *,
    source_names: Sequence[str],
    params: CandidateParams,
    mode: str,
    selected_profile: str | None,
) -> dict[str, Any]:
    params.validate()
    if mode not in {"DEVELOPMENT_COMPARE_ALL", "FROZEN_VALIDATION_ONE"}:
        raise ValueError(f"UNSUPPORTED_MODE:{mode}")
    if not source_names:
        raise ValueError("SOURCE_NAMES_REQUIRED")
    if mode == "FROZEN_VALIDATION_ONE":
        if not selected_profile or selected_profile not in CLEAN_PROFILES:
            raise ValueError("FROZEN_SELECTED_PROFILE_REQUIRED")
        active_profiles = (selected_profile,)
    else:
        if selected_profile:
            raise ValueError("DEVELOPMENT_MUST_NOT_PRESELECT_PROFILE")
        active_profiles = tuple(CLEAN_PROFILES)

    p5_rule = PRECISION_VARIANTS[BASE_VARIANT]
    lookback = max(params.effort_lookback, params.progress_lookback, params.high_lookback)
    variant_ids = tuple(variant_name(profile) for profile in active_profiles)

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
    context_unavailable_counts: dict[str, int] = {source: 0 for source in source_names}

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
                keep_dates = set(completed_market_dates[-(PRIOR_WINDOW + 2):])
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

                    if len(completed_market_dates) < PRIOR_WINDOW:
                        context_unavailable_counts[source_name] += 1
                        continue
                    prior_dates = completed_market_dates[-PRIOR_WINDOW:]
                    base_context = _history_context(
                        bars=bars,
                        index=i,
                        history_by_date=ticker_history,
                        prior_dates=prior_dates,
                    )
                    if base_context is None:
                        context_unavailable_counts[source_name] += 1
                        continue
                    context = _enrich_context(
                        base_context,
                        bars=bars,
                        index=i,
                        ticker_history=ticker_history,
                        prior_dates=prior_dates,
                    )
                    if context is None:
                        context_unavailable_counts[source_name] += 1
                        continue

                    for profile_name in active_profiles:
                        variant = variant_name(profile_name)
                        if variant in first_by_variant:
                            continue
                        if _profile_matches(context, CLEAN_PROFILES[profile_name]):
                            first_by_variant[variant] = (i, outcome, context, p5_features)

                for variant, (i, outcome, context, p5_features) in first_by_variant.items():
                    _add(aggregate[source_name][variant], outcome)
                    _add(daily[source_name][date][variant], outcome)
                    if len(samples[source_name][variant]) < 20:
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
        "schema": "A1_TELEGRAM_MG_CLEAN_V2_STUDY_V1",
        "status": "RESEARCH_CANDIDATE_NOT_FINAL" if mode == "DEVELOPMENT_COMPARE_ALL" else "FROZEN_OOS_VALIDATION_RESULT",
        "mode": mode,
        "selected_profile": selected_profile,
        "purpose": "FEWER_CLEANER_EARLY_POTENTIAL_SIGNALS_WITH_RELATIVE_STRENGTH_AND_ANTI_EXTENSION",
        "base_intraday_gate": BASE_VARIANT,
        "prior_window_trading_days": PRIOR_WINDOW,
        "profile_definitions": {name: CLEAN_PROFILES[name] for name in active_profiles},
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
            "No weighted score is used; each profile is an explicit conjunction of causal conditions.",
            "Development profiles are compared only on the declared development periods.",
            "FROZEN_VALIDATION_ONE evaluates exactly one previously selected profile and must not retune it.",
            "Reward evaluation is same-day only and starts after the publication bar.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-clean-v2-study")
    parser.add_argument("--source-name", action="append", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--selected-profile")
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
    report = build_clean_v2_study(
        source_names=args.source_name,
        params=params,
        mode=args.mode,
        selected_profile=args.selected_profile,
    )
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_CLEAN_V2_STUDY__{safe_request}.json", obj=report)
    print(dumps({"pass": True, "drive_artifact": uploaded, "summary": report["cross_period_stability"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
