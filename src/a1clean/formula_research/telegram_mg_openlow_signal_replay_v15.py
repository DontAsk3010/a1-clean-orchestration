from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import telegram_mg_daily_strength_v14 as v14
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_open_ladder_v13 import _eq, _five_vs_five_accel, _pct
from .telegram_mg_replay import _dynamic_targets, _is_publication_slot

SOURCE = "Raw Des 02-31-2024.csv"
SOURCE_LEVEL = 3.5
TARGET_LOOKBACK = 5
BUY_FEE_PCT = 0.15
SELL_FEE_PCT = 0.25


def _first_future_hit(bars: Sequence[Mapping[str, Any]], start: int, target: float | None) -> str | None:
    if target is None:
        return None
    for row in bars[start + 1:]:
        hi = row.get("high")
        if hi is not None and float(hi) >= float(target):
            ts = str(row.get("timestamp") or "")
            return ts[11:16] if len(ts) >= 16 else ts
    return None


def _net_pct(entry: float, exit_price: float) -> float:
    buy = entry * (1.0 + BUY_FEE_PCT / 100.0)
    sell = exit_price * (1.0 - SELL_FEE_PCT / 100.0)
    return (sell / buy - 1.0) * 100.0


def build_report() -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    src = next((x for x in sources if str(x["source_name"]) == SOURCE), None)
    if src is None or not v12r._meta_ok(SOURCE, src):
        raise RuntimeError("V15_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD")

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in v12r._iter_cached(SOURCE):
        bars = [dict(x) for x in packet.get("bars", [])]
        if bars:
            by_ticker[str(packet["ticker"])].append({"date": str(packet["date"]), "bars": bars})

    daily: dict[str, dict[str, Any]] = {}
    all_signals: list[dict[str, Any]] = []

    for ticker, days in by_ticker.items():
        days.sort(key=lambda x: x["date"])
        for di, day in enumerate(days):
            bars = day["bars"]
            date = day["date"]
            opens = [float(b["open"]) for b in bars if b.get("open") is not None]
            lows = [float(b["low"]) for b in bars if b.get("low") is not None]
            closes = [float(b["close"]) for b in bars if b.get("close") is not None]
            highs = [float(b["high"]) for b in bars if b.get("high") is not None]
            if not opens or not lows or not closes or not highs:
                continue
            op = opens[0]
            d = daily.setdefault(date, {"date": date, "openlow_scouts": set(), "signals": []})

            run_low = None
            pubs: list[dict[str, Any]] = []
            for i, row in enumerate(bars):
                lo = row.get("low")
                if lo is not None:
                    run_low = float(lo) if run_low is None else min(run_low, float(lo))
                if _is_publication_slot(row.get("timestamp")) and row.get("close") is not None and run_low is not None:
                    if _eq(run_low, op):
                        d["openlow_scouts"].add(ticker)
                    pubs.append({
                        "i": i,
                        "timestamp": str(row.get("timestamp") or ""),
                        "close": float(row["close"]),
                        "run_low": run_low,
                    })

            if di == 0:
                continue
            prev_closes = [float(b["close"]) for b in days[di - 1]["bars"] if b.get("close") is not None]
            if not prev_closes or prev_closes[-1] <= 0:
                continue
            prev_close = prev_closes[-1]
            for p in pubs:
                p["chg_pct"] = _pct(p["close"], prev_close)

            cross_pos = None
            for pos, p in enumerate(pubs):
                prev_path = pubs[pos - 1]["chg_pct"] if pos else None
                if p["chg_pct"] >= SOURCE_LEVEL and (prev_path is None or prev_path < SOURCE_LEVEL):
                    cross_pos = pos
                    break
            if cross_pos is None or cross_pos + 1 >= len(pubs):
                continue

            cross = pubs[cross_pos]
            conf = pubs[cross_pos + 1]
            ci = int(conf["i"])
            # Causal V15 structure: Open remains running low, 3.5% survives one publication,
            # confirmation does not give back versus crossing close, and existing 5-vs-5 effort accelerates.
            if not _eq(conf["run_low"], op):
                continue
            if conf["chg_pct"] < SOURCE_LEVEL:
                continue
            if conf["close"] < cross["close"]:
                continue
            if not _five_vs_five_accel(bars, ci):
                continue

            tp1, tp2, step = _dynamic_targets(bars, ci, TARGET_LOOKBACK)
            if tp1 is None or tp2 is None:
                continue
            tp1_hit_time = _first_future_hit(bars, ci, tp1)
            tp2_hit_time = _first_future_hit(bars, ci, tp2)
            future_high = max((float(b["high"]) for b in bars[ci + 1:] if b.get("high") is not None), default=conf["close"])
            eod = closes[-1]
            row = {
                "date": date,
                "ticker": ticker,
                "signal_timestamp": conf["timestamp"],
                "time": conf["timestamp"][11:16] if len(conf["timestamp"]) >= 16 else conf["timestamp"],
                "price": conf["close"],
                "chg_pct": conf["chg_pct"],
                "tp1": tp1,
                "tp2": tp2,
                "tp1_hit": tp1_hit_time is not None,
                "tp1_hit_time": tp1_hit_time,
                "tp2_hit": tp2_hit_time is not None,
                "tp2_hit_time": tp2_hit_time,
                "net_tp1_pct": _net_pct(conf["close"], tp1) if tp1_hit_time else None,
                "net_tp2_pct": _net_pct(conf["close"], tp2) if tp2_hit_time else None,
                "max_future_pct_from_signal": (future_high / conf["close"] - 1.0) * 100.0,
                "eod_pct_from_signal": (eod / conf["close"] - 1.0) * 100.0,
                "target_step": step,
                "decision_state": {
                    "open_eq_running_low": True,
                    "cross_3_5_survived_next_publication": True,
                    "confirmation_close_not_below_cross": True,
                    "five_vs_five_effort_acceleration": True,
                },
            }
            d["signals"].append(row)
            all_signals.append(row)

    days_out = []
    for date in sorted(daily):
        d = daily[date]
        signals = sorted(d["signals"], key=lambda r: (r["time"], r["ticker"]))
        days_out.append({
            "date": date,
            "openlow_scout_count": len(d["openlow_scouts"]),
            "openlow_scout_tickers": sorted(d["openlow_scouts"]),
            "signal_count": len(signals),
            "tp1_hit_count": sum(bool(r["tp1_hit"]) for r in signals),
            "tp2_hit_count": sum(bool(r["tp2_hit"]) for r in signals),
            "signals": signals,
        })

    return {
        "schema": "A1_TELEGRAM_MG_OPENLOW_SIGNAL_REPLAY_V15_RESULT_V1",
        "mode": "REPLAY",
        "source": SOURCE,
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "signal_structure": "OPEN_EQ_RUNNING_LOW -> 3.5_CROSS -> NEXT_5MIN_HOLD -> NO_GIVEBACK -> 5V5_EFFORT_ACCELERATION",
        "target_policy": "EXISTING_DYNAMIC_LOCAL_RANGE_PLUS_OBSERVED_HIGH",
        "telegram_columns": ["CODE", "PRICE", "CHG%", "TP-1", "TP-2"],
        "signal_total": len(all_signals),
        "tp1_hit_total": sum(bool(r["tp1_hit"]) for r in all_signals),
        "tp2_hit_total": sum(bool(r["tp2_hit"]) for r in all_signals),
        "days": days_out,
        "future_data_used_for_signal_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    a = p.parse_args()
    report = build_report()
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "signal_total": report["signal_total"],
        "tp1_hit_total": report["tp1_hit_total"],
        "tp2_hit_total": report["tp2_hit_total"],
        "days": len(report["days"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
