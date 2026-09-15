from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_precision_study import (
    PRECISION_VARIANTS,
    _candidate_features,
    _variant_matches,
)
from .telegram_mg_replay import _num, evaluate_mg_packet
from .telegram_mg_reward_audit import _evaluate_future, _summary


def _clock(timestamp: Any) -> str:
    if timestamp is None:
        return "UNKNOWN"
    try:
        return datetime.fromisoformat(str(timestamp)).strftime("%H:%M")
    except ValueError:
        return str(timestamp)


def _last_close(bars: list[dict[str, Any]]) -> float | None:
    for row in reversed(bars):
        value = _num(row.get("close"))
        if value is not None and value > 0:
            return float(value)
    return None


def _date_order(reader: GovernedSourceReader) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    prior = ""
    for row in reader.semantic_manifest_rows:
        date = str(row.trading_date)
        if prior and date < prior:
            raise ValueError(f"SEMANTIC_MANIFEST_TRADING_DATE_NOT_MONOTONIC:{prior}>{date}")
        prior = date
        if date not in seen:
            seen.add(date)
            ordered.append(date)
    return tuple(ordered)


def build_full_precision_report(
    *, source_name: str, variant: str, params: CandidateParams
) -> dict[str, Any]:
    params.validate()
    if variant not in PRECISION_VARIANTS:
        raise ValueError(f"UNKNOWN_PRECISION_VARIANT:{variant}")

    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    trading_dates = _date_order(reader)
    date_position = {date: i for i, date in enumerate(trading_dates)}
    lookback = max(params.effort_lookback, params.progress_lookback, params.high_lookback)
    rule = PRECISION_VARIANTS[variant]

    rows: list[dict[str, Any]] = []
    last_close_by_ticker: dict[str, tuple[str, float]] = {}
    packet_count = 0
    eligible_packet_count = 0

    for _manifest_row, packet in reader.iter_packets():
        packet_count += 1
        ticker = str(packet.identity.ticker)
        date = str(packet.identity.trading_date)
        all_bars, _mapping = packet_to_formula_bars(packet)
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        if not bars:
            continue
        eligible_packet_count += 1

        previous_close = None
        prior = last_close_by_ticker.get(ticker)
        if prior is not None:
            prior_date, prior_close = prior
            if date_position.get(prior_date, -2) == date_position.get(date, -1) - 1:
                previous_close = prior_close

        mg_rows = evaluate_mg_packet(bars, params)
        selected: tuple[int, dict[str, Any], dict[str, Any]] | None = None
        for i, mg in enumerate(mg_rows):
            if not mg.get("publication_slot"):
                continue
            if mg["variants"].get("MG_B_PATH_VALUE") != TRUE:
                continue
            entry = _num(bars[i].get("close"))
            tp1 = _num(mg["targets"].get("tp1"))
            tp2 = _num(mg["targets"].get("tp2"))
            if entry is None or entry <= 0 or tp1 is None or tp2 is None:
                continue
            features = _candidate_features(bars, i, lookback=lookback)
            if not _variant_matches(features, rule):
                continue
            outcome = _evaluate_future(
                bars, i, entry=float(entry), tp1=float(tp1), tp2=float(tp2)
            )
            selected = (i, mg, {**features, **outcome})
            break

        if selected is not None:
            i, mg, enriched = selected
            entry = float(bars[i]["close"])
            chg = (
                (entry / previous_close - 1.0) * 100.0
                if previous_close is not None and previous_close > 0
                else None
            )
            rows.append(
                {
                    "trading_date": date,
                    "as_of": bars[i].get("timestamp"),
                    "display_time": _clock(bars[i].get("timestamp")),
                    "CODE": ticker,
                    "PRICE": entry,
                    "CHG%": chg,
                    "TP-1": float(mg["targets"]["tp1"]),
                    "TP-2": float(mg["targets"]["tp2"]),
                    "session_segment": enriched.get("session_segment"),
                    "recent_return_pct": enriched.get("recent_return_pct"),
                    "local_range_step_pct": enriched.get("local_range_step_pct"),
                    "recent_non_down_ratio": enriched.get("recent_non_down_ratio"),
                    "result": enriched["result"],
                    "tp1_hit": enriched["tp1_hit"],
                    "tp2_hit": enriched["tp2_hit"],
                    "tp1_hit_time": enriched["tp1_hit_time"],
                    "tp2_hit_time": enriched["tp2_hit_time"],
                    "max_future_high": enriched["max_future_high"],
                    "min_future_low": enriched["min_future_low"],
                    "max_reward_pct": enriched["max_reward_pct"],
                    "max_drawdown_pct": enriched["max_drawdown_pct"],
                    "close_price": enriched["close_price"],
                    "close_return_pct": enriched["close_return_pct"],
                }
            )

        close = _last_close(bars)
        if close is not None:
            last_close_by_ticker[ticker] = (date, close)

    rows.sort(key=lambda row: (row["trading_date"], row["as_of"], row["CODE"]))
    daily_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        daily_rows[str(row["trading_date"])].append(row)

    daily_summary = {date: _summary(items) for date, items in sorted(daily_rows.items())}
    daily_result_codes = {
        date: {
            result: sorted(row["CODE"] for row in items if row["result"] == result)
            for result in ("TP2", "TP1_ONLY", "NO_TP", "NO_FUTURE_BAR")
        }
        for date, items in sorted(daily_rows.items())
    }
    slots: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        slots[str(row["trading_date"])][str(row["display_time"])].append(row)

    result_counts = Counter(str(row["result"]) for row in rows)
    return {
        "schema": "A1_TELEGRAM_MG_PRECISION_FULL_REWARD_REPORT_V1",
        "status": "RESEARCH_REPORT_NOT_CANONICAL",
        "telegram_family": "EARLY_POTENTIAL",
        "telegram_public_name": "MULAI GENIT",
        "telegram_output_contract": "CODE | PRICE | CHG% | TP-1 | TP-2",
        "source_name": source_name,
        "variant": variant,
        "variant_rule": rule,
        "params": params.__dict__,
        "trading_dates": list(trading_dates),
        "packet_count": packet_count,
        "eligible_packet_count": eligible_packet_count,
        "first_alert_count": len(rows),
        "evaluation_window": "NEXT_REGULAR_BAR_AFTER_FIRST_5M_ALERT_THROUGH_SAME_DAY_CLOSE",
        "same_alert_bar_high_counted": False,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_evaluation_only": True,
        "monthly_summary": _summary(rows),
        "result_counts": dict(result_counts),
        "daily_summary": daily_summary,
        "daily_result_codes": daily_result_codes,
        "first_alerts": rows,
        "first_alerts_by_5m_slot": {
            date: {time: slot_rows for time, slot_rows in sorted(times.items())}
            for date, times in sorted(slots.items())
        },
        "final_or_canonical_claim": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-precision-full-report")
    parser.add_argument("--source-name", required=True)
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
    report = build_full_precision_report(
        source_name=args.source_name, variant=args.variant, params=params
    )
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(
        name=f"TELEGRAM_MG_PRECISION_FULL_REPORT__{safe_request}.json", obj=report
    )
    print(json.dumps({"pass": True, "report_summary": report["monthly_summary"], "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
