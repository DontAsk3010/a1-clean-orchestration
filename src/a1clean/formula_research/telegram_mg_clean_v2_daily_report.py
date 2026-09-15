from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_clean_v2_study import (
    BASE_VARIANT,
    CLEAN_PROFILES,
    PRIOR_WINDOW,
    _enrich_context,
    _profile_matches,
    variant_name,
)
from .telegram_mg_multiday_context_study import DayRecord, _history_context, _num
from .telegram_mg_precision_study import (
    PRECISION_VARIANTS,
    _candidate_features,
    _variant_matches,
)
from .telegram_mg_replay import evaluate_mg_packet


def _outcome_with_hit_times(
    bars: Sequence[Mapping[str, Any]],
    index: int,
    *,
    entry: float,
    tp1: float,
    tp2: float,
) -> dict[str, Any]:
    future = bars[index + 1 :]
    if not future:
        return {
            "evaluable": False,
            "result": "NO_FUTURE_BAR",
            "tp1_hit": False,
            "tp2_hit": False,
            "tp1_hit_time": None,
            "tp2_hit_time": None,
            "max_high": None,
            "max_reward_pct": None,
            "max_drawdown_pct": None,
            "close": None,
            "close_return_pct": None,
        }

    tp1_hit_time = None
    tp2_hit_time = None
    high_values: list[float] = []
    low_values: list[float] = []
    close_values: list[float] = []
    for row in future:
        high = _num(row.get("high"))
        low = _num(row.get("low"))
        close = _num(row.get("close"))
        timestamp = row.get("timestamp")
        if high is not None:
            high_values.append(high)
            if tp1_hit_time is None and high >= tp1:
                tp1_hit_time = timestamp
            if tp2_hit_time is None and high >= tp2:
                tp2_hit_time = timestamp
        if low is not None:
            low_values.append(low)
        if close is not None:
            close_values.append(close)

    if not high_values or not low_values:
        return {
            "evaluable": False,
            "result": "NO_FUTURE_BAR",
            "tp1_hit": False,
            "tp2_hit": False,
            "tp1_hit_time": None,
            "tp2_hit_time": None,
            "max_high": None,
            "max_reward_pct": None,
            "max_drawdown_pct": None,
            "close": None,
            "close_return_pct": None,
        }

    max_high = max(high_values)
    min_low = min(low_values)
    final_close = close_values[-1] if close_values else entry
    tp1_hit = tp1_hit_time is not None
    tp2_hit = tp2_hit_time is not None
    return {
        "evaluable": True,
        "result": "TP2" if tp2_hit else ("TP1_ONLY" if tp1_hit else "NO_TP"),
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "tp1_hit_time": tp1_hit_time,
        "tp2_hit_time": tp2_hit_time,
        "max_high": max_high,
        "max_reward_pct": (max_high / entry - 1.0) * 100.0,
        "max_drawdown_pct": (min_low / entry - 1.0) * 100.0,
        "close": final_close,
        "close_return_pct": (final_close / entry - 1.0) * 100.0,
    }


def build_clean_v2_daily_report(
    *,
    source_names: Sequence[str],
    trading_date: str,
    profile: str,
    params: CandidateParams,
) -> dict[str, Any]:
    params.validate()
    if profile not in CLEAN_PROFILES:
        raise ValueError(f"UNKNOWN_CLEAN_PROFILE:{profile}")
    if len(source_names) < 2:
        raise ValueError("AT_LEAST_TWO_CHRONOLOGICAL_SOURCES_REQUIRED")

    p5_rule = PRECISION_VARIANTS[BASE_VARIANT]
    lookback = max(params.effort_lookback, params.progress_lookback, params.high_lookback)
    variant = variant_name(profile)

    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_market_dates: list[str] = []
    current_market_date: str | None = None
    seen_market_dates: set[str] = set()
    target_packets: dict[str, list[dict[str, Any]]] = {}
    target_context_history: dict[str, dict[str, DayRecord]] = {}
    scanned_packets = 0
    target_seen = False

    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        stop_source = False
        for _manifest_row, packet in reader.iter_packets():
            date = str(packet.identity.trading_date)
            if target_seen and date > trading_date:
                stop_source = True
                break

            if current_market_date is None:
                current_market_date = date
            elif date != current_market_date:
                if current_market_date not in seen_market_dates:
                    completed_market_dates.append(current_market_date)
                    seen_market_dates.add(current_market_date)
                current_market_date = date
                keep_dates = set(completed_market_dates[-(PRIOR_WINDOW + 2) :])
                for ticker in list(history):
                    history[ticker] = {d: rec for d, rec in history[ticker].items() if d in keep_dates}
                    if not history[ticker]:
                        del history[ticker]

            all_bars, _mapping = packet_to_formula_bars(packet)
            bars = [bar for bar in all_bars if bar["session_eligible"]]
            scanned_packets += 1
            ticker = str(packet.identity.ticker)

            if date < trading_date:
                if bars:
                    history.setdefault(ticker, {})[date] = DayRecord(
                        trading_date=date,
                        bars=tuple(dict(bar) for bar in bars),
                    )
                continue

            if date == trading_date:
                target_seen = True
                if bars:
                    target_packets[ticker] = bars
                    target_context_history[ticker] = dict(history.get(ticker, {}))
                continue

        if stop_source:
            break

    if not target_packets:
        raise ValueError(f"TARGET_DATE_NOT_FOUND:{trading_date}")

    slot_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    slot_suppressed_context: dict[str, list[str]] = defaultdict(list)
    all_slots: set[str] = set()
    first_appearance_audit: dict[str, dict[str, Any]] = {}

    if len(completed_market_dates) < PRIOR_WINDOW:
        raise ValueError("PRIOR_MARKET_DATES_UNAVAILABLE")
    prior_dates = completed_market_dates[-PRIOR_WINDOW:]

    for ticker, bars in target_packets.items():
        ticker_history = target_context_history.get(ticker, {})
        mg_rows = evaluate_mg_packet(bars, params)
        for i, mg in enumerate(mg_rows):
            if not mg.get("publication_slot"):
                continue
            timestamp = str(mg.get("timestamp"))
            all_slots.add(timestamp)
            if mg["variants"].get("MG_B_PATH_VALUE") != TRUE:
                continue
            p5_features = _candidate_features(bars, i, lookback=lookback)
            if not _variant_matches(p5_features, p5_rule):
                continue
            base_context = _history_context(
                bars=bars,
                index=i,
                history_by_date=ticker_history,
                prior_dates=prior_dates,
            )
            if base_context is None:
                slot_suppressed_context[timestamp].append(ticker)
                continue
            context = _enrich_context(
                base_context,
                bars=bars,
                index=i,
                ticker_history=ticker_history,
                prior_dates=prior_dates,
            )
            if context is None:
                slot_suppressed_context[timestamp].append(ticker)
                continue
            if not _profile_matches(context, CLEAN_PROFILES[profile]):
                continue

            entry = _num(bars[i].get("close"))
            tp1 = _num(mg["targets"].get("tp1"))
            tp2 = _num(mg["targets"].get("tp2"))
            if entry is None or entry <= 0 or tp1 is None or tp2 is None:
                continue
            previous_close = _num(context.get("previous_regular_close"))
            chg_pct = (
                (entry / previous_close - 1.0) * 100.0
                if previous_close is not None and previous_close > 0
                else None
            )
            row = {
                "CODE": ticker,
                "PRICE": entry,
                "CHG%": chg_pct,
                "TP-1": tp1,
                "TP-2": tp2,
            }
            slot_rows[timestamp].append(row)

            if ticker not in first_appearance_audit:
                first_appearance_audit[ticker] = {
                    "TIME": timestamp,
                    **row,
                    **_outcome_with_hit_times(
                        bars,
                        i,
                        entry=entry,
                        tp1=tp1,
                        tp2=tp2,
                    ),
                }

    slots: list[dict[str, Any]] = []
    previous_codes: set[str] = set()
    seen_codes: set[str] = set()
    for timestamp in sorted(all_slots):
        rows = sorted(slot_rows.get(timestamp, []), key=lambda row: str(row["CODE"]))
        current_codes = {str(row["CODE"]) for row in rows}
        new_codes = sorted(current_codes - seen_codes)
        returned_codes = sorted((current_codes - previous_codes) & seen_codes)
        continued_codes = sorted(current_codes & previous_codes)
        dropped_codes = sorted(previous_codes - current_codes)
        slots.append(
            {
                "as_of": timestamp,
                "display_time": datetime.fromisoformat(timestamp).strftime("%H:%M"),
                "candidate_count": len(rows),
                "new_codes": new_codes,
                "continued_codes": continued_codes,
                "returned_codes": returned_codes,
                "dropped_codes": dropped_codes,
                "suppressed_context_unavailable": sorted(slot_suppressed_context.get(timestamp, [])),
                "telegram_zero_match_render": "========" if not rows else None,
                "rows": rows,
            }
        )
        seen_codes.update(current_codes)
        previous_codes = current_codes

    audits = sorted(first_appearance_audit.values(), key=lambda row: (str(row["TIME"]), str(row["CODE"])))
    summary = {
        "first_appearance_count": len(audits),
        "evaluable_count": sum(int(bool(row.get("evaluable"))) for row in audits),
        "tp2_count": sum(int(row.get("result") == "TP2") for row in audits),
        "tp1_only_count": sum(int(row.get("result") == "TP1_ONLY") for row in audits),
        "no_tp_count": sum(int(row.get("result") == "NO_TP") for row in audits),
    }

    return {
        "schema": "A1_TELEGRAM_MG_CLEAN_V2_DAILY_5M_TAPE_V1",
        "status": "RESEARCH_REPORT_NOT_CANONICAL",
        "trading_date": trading_date,
        "profile": profile,
        "variant": variant,
        "telegram_family": "EARLY_POTENTIAL",
        "telegram_public_name": "MULAI_GENIT",
        "telegram_output_contract": "CODE | PRICE | CHG% | TP-1 | TP-2",
        "telegram_publication_policy": "EVERY_5_MINUTES_FROM_09_00_WIB_THROUGH_AVAILABLE_REGULAR_SESSION_SLOTS",
        "zero_match_render": "========",
        "prior_dates_used": list(prior_dates),
        "scanned_source_packets": scanned_packets,
        "target_ticker_count": len(target_packets),
        "slot_count": len(slots),
        "slots": slots,
        "first_appearance_audit": audits,
        "summary": summary,
        "future_data_used_for_candidate_state": False,
        "future_data_used_for_outcome_audit_only": True,
        "same_alert_bar_high_counted_for_reward": False,
        "h_plus_1_used_to_qualify_mg": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-clean-v2-daily-report")
    parser.add_argument("--source-name", action="append", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--profile", required=True)
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
    report = build_clean_v2_daily_report(
        source_names=args.source_name,
        trading_date=args.trading_date,
        profile=args.profile,
        params=params,
    )
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(
        name=f"TELEGRAM_MG_CLEAN_V2_DAILY_REPORT__{safe_request}.json",
        obj=report,
    )
    print(json.dumps({"pass": True, "report": report, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
