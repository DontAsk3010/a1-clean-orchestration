from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import telegram_mg_daily_strength_v14 as v14
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_replay import _is_publication_slot


def _eq(a: float | None, b: float | None, eps: float = 1e-9) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= eps


def _all_day_open_low_scan() -> list[dict[str, Any]]:
    sources = v11._ordered_governed_sources()
    src = next((x for x in sources if str(x["source_name"]) == v14.SOURCE), None)
    if src is None or not v12r._meta_ok(v14.SOURCE, src):
        raise RuntimeError("V14B_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD")
    daily: dict[str, dict[str, Any]] = {}
    for packet in v12r._iter_cached(v14.SOURCE):
        bars = [dict(x) for x in packet.get("bars", [])]
        if not bars:
            continue
        ticker = str(packet["ticker"])
        date = str(packet["date"])
        opens = [float(b["open"]) for b in bars if b.get("open") is not None]
        lows = [float(b["low"]) for b in bars if b.get("low") is not None]
        highs = [float(b["high"]) for b in bars if b.get("high") is not None]
        closes = [float(b["close"]) for b in bars if b.get("close") is not None]
        if not opens or not lows or not highs or not closes or max(highs) <= min(lows):
            continue
        op = opens[0]
        d = daily.setdefault(date, {
            "date": date,
            "open_eq_low_final_tickers": [],
            "open_running_low_by_snapshot": defaultdict(list),
        })
        if _eq(op, min(lows)):
            d["open_eq_low_final_tickers"].append(ticker)
        run_low = None
        for bar in bars:
            lo = bar.get("low")
            if lo is not None:
                run_low = float(lo) if run_low is None else min(run_low, float(lo))
            if _is_publication_slot(bar.get("timestamp")) and run_low is not None and _eq(run_low, op):
                d["open_running_low_by_snapshot"][str(bar.get("timestamp"))].append(ticker)
    out = []
    for date in sorted(daily):
        d = daily[date]
        out.append({
            "date": date,
            "open_eq_low_final_count": len(d["open_eq_low_final_tickers"]),
            "open_eq_low_final_tickers": sorted(d["open_eq_low_final_tickers"]),
            "open_running_low_by_snapshot": {
                k: sorted(v) for k, v in sorted(d["open_running_low_by_snapshot"].items())
            },
        })
    return out


def build_report() -> dict[str, Any]:
    report = v14.build_report()
    all_days = _all_day_open_low_scan()
    report["schema"] = "A1_TELEGRAM_MG_DAILY_STRENGTH_V14B_RESULT_V1"
    report["all_trading_days_open_low_scan"] = all_days
    report["open_low_all_dates_count"] = len(all_days)
    report["open_eq_low_final_total_all_dates"] = sum(x["open_eq_low_final_count"] for x in all_days)
    report["telegram_research_contract"]["open_low_scan_covers_every_available_trading_date"] = True
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    a = p.parse_args()
    report = build_report()
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "strong10_total": report["strong10_total"],
        "strong10_hit12": report["strong10_hit12"],
        "strong10_fail12": report["strong10_fail12"],
        "strong10_hit12_rate": report["strong10_hit12_rate"],
        "open_low_all_dates_count": report["open_low_all_dates_count"],
        "open_eq_low_final_total_all_dates": report["open_eq_low_final_total_all_dates"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
