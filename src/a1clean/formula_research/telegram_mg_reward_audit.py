from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams
from .telegram_mg_daily_report import build_daily_report
from .telegram_mg_replay import _num


def _evaluate_future(
    bars: list[dict[str, Any]], index: int, *, entry: float, tp1: float, tp2: float
) -> dict[str, Any]:
    future = bars[index + 1 :]
    if not future:
        return {
            "result": "NO_FUTURE_BAR",
            "tp1_hit": False,
            "tp2_hit": False,
            "tp1_hit_time": None,
            "tp2_hit_time": None,
            "max_future_high": None,
            "min_future_low": None,
            "max_reward_pct": None,
            "max_drawdown_pct": None,
            "close_price": entry,
            "close_return_pct": 0.0,
        }

    highs = [float(v) for v in (_num(row.get("high")) for row in future) if v is not None]
    lows = [float(v) for v in (_num(row.get("low")) for row in future) if v is not None]
    closes = [float(v) for v in (_num(row.get("close")) for row in future) if v is not None]
    max_high = max(highs) if highs else None
    min_low = min(lows) if lows else None
    close_price = closes[-1] if closes else entry

    tp1_time = None
    tp2_time = None
    for row in future:
        high = _num(row.get("high"))
        if high is None:
            continue
        if tp1_time is None and high >= tp1:
            tp1_time = row.get("timestamp")
        if tp2_time is None and high >= tp2:
            tp2_time = row.get("timestamp")
        if tp1_time is not None and tp2_time is not None:
            break

    tp1_hit = tp1_time is not None
    tp2_hit = tp2_time is not None
    result = "TP2" if tp2_hit else ("TP1_ONLY" if tp1_hit else "NO_TP")
    return {
        "result": result,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "tp1_hit_time": tp1_time,
        "tp2_hit_time": tp2_time,
        "max_future_high": max_high,
        "min_future_low": min_low,
        "max_reward_pct": ((max_high / entry - 1.0) * 100.0) if max_high is not None and entry > 0 else None,
        "max_drawdown_pct": ((min_low / entry - 1.0) * 100.0) if min_low is not None and entry > 0 else None,
        "close_price": close_price,
        "close_return_pct": (close_price / entry - 1.0) * 100.0 if entry > 0 else None,
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["result"]) for row in rows)
    n = len(rows)
    evaluable = [row for row in rows if row["result"] != "NO_FUTURE_BAR"]
    e = len(evaluable)
    positive_close = sum(1 for row in evaluable if (row.get("close_return_pct") or 0.0) > 0)
    any_positive_excursion = sum(1 for row in evaluable if (row.get("max_reward_pct") or 0.0) > 0)
    avg_reward = (
        sum(float(row["max_reward_pct"]) for row in evaluable if row.get("max_reward_pct") is not None)
        / sum(1 for row in evaluable if row.get("max_reward_pct") is not None)
        if any(row.get("max_reward_pct") is not None for row in evaluable)
        else None
    )
    avg_dd = (
        sum(float(row["max_drawdown_pct"]) for row in evaluable if row.get("max_drawdown_pct") is not None)
        / sum(1 for row in evaluable if row.get("max_drawdown_pct") is not None)
        if any(row.get("max_drawdown_pct") is not None for row in evaluable)
        else None
    )
    avg_close = (
        sum(float(row["close_return_pct"]) for row in evaluable if row.get("close_return_pct") is not None)
        / sum(1 for row in evaluable if row.get("close_return_pct") is not None)
        if any(row.get("close_return_pct") is not None for row in evaluable)
        else None
    )
    return {
        "row_count": n,
        "evaluable_count": e,
        "tp2_count": counts.get("TP2", 0),
        "tp1_only_count": counts.get("TP1_ONLY", 0),
        "no_tp_count": counts.get("NO_TP", 0),
        "no_future_bar_count": counts.get("NO_FUTURE_BAR", 0),
        "tp1_or_better_rate": ((counts.get("TP1_ONLY", 0) + counts.get("TP2", 0)) / e) if e else None,
        "tp2_rate": (counts.get("TP2", 0) / e) if e else None,
        "positive_close_rate": (positive_close / e) if e else None,
        "any_positive_excursion_rate": (any_positive_excursion / e) if e else None,
        "mean_max_reward_pct": avg_reward,
        "mean_max_drawdown_pct": avg_dd,
        "mean_close_return_pct": avg_close,
    }


def build_reward_audit(
    *, source_name: str, trading_date: str, variant: str, params: CandidateParams
) -> dict[str, Any]:
    daily = build_daily_report(
        source_name=source_name,
        trading_date=trading_date,
        variant=variant,
        params=params,
    )

    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    bars_by_ticker: dict[str, list[dict[str, Any]]] = {}
    index_by_ticker_time: dict[str, dict[str, int]] = {}
    for _manifest_row, packet in reader.iter_packets():
        if str(packet.identity.trading_date) != trading_date:
            continue
        all_bars, _mapping = packet_to_formula_bars(packet)
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        if not bars:
            continue
        ticker = str(packet.identity.ticker)
        bars_by_ticker[ticker] = bars
        index_by_ticker_time[ticker] = {str(bar.get("timestamp")): i for i, bar in enumerate(bars)}

    appearances: list[dict[str, Any]] = []
    first_by_ticker: dict[str, dict[str, Any]] = {}
    episode_firsts: list[dict[str, Any]] = []
    active_prev: set[str] = set()

    for slot in daily["slots"]:
        current = {str(row["CODE"]) for row in slot["rows"]}
        for row in slot["rows"]:
            ticker = str(row["CODE"])
            timestamp = str(slot["as_of"])
            entry = float(row["PRICE"])
            tp1 = float(row["TP-1"])
            tp2 = float(row["TP-2"])
            bars = bars_by_ticker.get(ticker, [])
            idx = index_by_ticker_time.get(ticker, {}).get(timestamp)
            if idx is None:
                outcome = {
                    "result": "NO_FUTURE_BAR", "tp1_hit": False, "tp2_hit": False,
                    "tp1_hit_time": None, "tp2_hit_time": None, "max_future_high": None,
                    "min_future_low": None, "max_reward_pct": None, "max_drawdown_pct": None,
                    "close_price": entry, "close_return_pct": 0.0,
                }
            else:
                outcome = _evaluate_future(bars, idx, entry=entry, tp1=tp1, tp2=tp2)
            enriched = {
                "as_of": timestamp,
                "display_time": slot["display_time"],
                "CODE": ticker,
                "PRICE": entry,
                "CHG%": row.get("CHG%"),
                "TP-1": tp1,
                "TP-2": tp2,
                "lifecycle": (
                    "NEW" if ticker in slot["new_codes"] else
                    "RETURN" if ticker in slot["returned_codes"] else
                    "CONTINUE"
                ),
                **outcome,
            }
            appearances.append(enriched)
            first_by_ticker.setdefault(ticker, enriched)
            if ticker not in active_prev:
                episode_firsts.append(enriched)
        active_prev = current

    first_rows = sorted(first_by_ticker.values(), key=lambda r: (r["as_of"], r["CODE"]))
    return {
        "schema": "A1_TELEGRAM_MG_REWARD_AUDIT_V1",
        "status": "RESEARCH_REPORT_NOT_CANONICAL",
        "telegram_family": daily["telegram_family"],
        "telegram_public_name": daily["telegram_public_name"],
        "trading_date": trading_date,
        "variant": variant,
        "evaluation_window": "NEXT_REGULAR_BAR_AFTER_TELEGRAM_SNAPSHOT_THROUGH_SAME_DAY_CLOSE",
        "same_bar_high_not_counted": True,
        "appearance_summary": _summary(appearances),
        "episode_first_summary": _summary(episode_firsts),
        "first_appearance_per_ticker_summary": _summary(first_rows),
        "first_appearance_per_ticker": first_rows,
        "episode_first_appearances": episode_firsts,
        "all_5m_appearances": appearances,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_evaluation_only": True,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-reward-audit")
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
    report = build_reward_audit(
        source_name=args.source_name,
        trading_date=args.trading_date,
        variant=args.variant,
        params=params,
    )
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_REWARD_AUDIT__{safe_request}.json", obj=report)
    print(json.dumps({"pass": True, "report": report, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
