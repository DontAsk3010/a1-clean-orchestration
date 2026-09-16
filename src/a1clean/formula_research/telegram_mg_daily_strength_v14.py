from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_replay import _is_publication_slot

SOURCE = "Raw Des 02-31-2024.csv"
UP_LADDER = (3.5, 4.0, 5.0, 5.7, 7.0, 10.0, 12.0)


def _pct(price: float, base: float) -> float:
    return (float(price) / float(base) - 1.0) * 100.0


def _eq(a: float | None, b: float | None, eps: float = 1e-9) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= eps


def _first_touch(bars: Sequence[Mapping[str, Any]], level: float) -> int | None:
    for i, bar in enumerate(bars):
        hi = bar.get("high")
        if hi is not None and float(hi) >= level:
            return i
    return None


def _strong_components(bars: Sequence[Mapping[str, Any]], idx: int) -> dict[str, Any]:
    bar = bars[idx]
    high, low, close, open_ = bar.get("high"), bar.get("low"), bar.get("close"), bar.get("open")
    if None in (high, low, close):
        return {"strong": False}
    high, low, close = float(high), float(low), float(close)
    if high <= low:
        return {"strong": False}
    location = (close - low) / (high - low)
    directional_location = location >= 0.5
    directional_vs_bar_open = open_ is None or close >= float(open_)
    prior_values = [
        float(b["trade_value"])
        for b in bars[max(0, idx - 5):idx]
        if b.get("flow_available") and b.get("trade_value") is not None
    ]
    this_value = (
        float(bar["trade_value"])
        if bar.get("flow_available") and bar.get("trade_value") is not None
        else None
    )
    median_prior_value = statistics.median(prior_values) if prior_values else None
    if median_prior_value is not None and this_value is not None:
        value_expansion = this_value > median_prior_value
        value_ratio = this_value / median_prior_value if median_prior_value > 0 else None
        strength_basis = "PRICE_AND_VALUE"
    else:
        value_expansion = True
        value_ratio = None
        strength_basis = "PRICE_ONLY_FLOW_UNAVAILABLE"
    return {
        "strong": bool(directional_location and directional_vs_bar_open and value_expansion),
        "bar_close_location": location,
        "directional_location": directional_location,
        "directional_vs_bar_open": directional_vs_bar_open,
        "value_expansion": value_expansion,
        "trade_value": this_value,
        "prior5_trade_value_median": median_prior_value,
        "trade_value_ratio_vs_prior5_median": value_ratio,
        "strength_basis": strength_basis,
    }


def _median(values: Sequence[float | int | None]) -> float | None:
    vals = [float(x) for x in values if x is not None]
    return float(statistics.median(vals)) if vals else None


def _clock(bar: Mapping[str, Any]) -> str | None:
    ts = bar.get("timestamp")
    return None if ts is None else str(ts)


def _summarize_group(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0}
    def rate(key: str) -> float:
        return sum(bool(r.get(key)) for r in rows) / n
    return {
        "n": n,
        "open_eq_low_final_rate": rate("open_eq_low_final"),
        "open_running_low_at_10_rate": rate("open_running_low_at_10"),
        "retained_10_next_publication_rate": rate("retained_10_next_publication"),
        "price_and_value_strength_rate": sum(r.get("strength_basis") == "PRICE_AND_VALUE" for r in rows) / n,
        "median_cross_bar_close_location": _median([r.get("bar_close_location") for r in rows]),
        "median_trade_value_ratio_vs_prior5": _median([r.get("trade_value_ratio_vs_prior5_median") for r in rows]),
        "median_bars_3_5_to_5": _median([r.get("bars_3_5_to_5") for r in rows]),
        "median_bars_5_to_5_7": _median([r.get("bars_5_to_5_7") for r in rows]),
        "median_bars_5_7_to_7": _median([r.get("bars_5_7_to_7") for r in rows]),
        "median_bars_7_to_10": _median([r.get("bars_7_to_10") for r in rows]),
        "median_eod_chg_pct": _median([r.get("eod_chg_pct") for r in rows]),
        "median_max_chg_pct": _median([r.get("max_chg_pct") for r in rows]),
    }


def build_report() -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    src = next((x for x in sources if str(x["source_name"]) == SOURCE), None)
    if src is None:
        raise RuntimeError(f"SOURCE_NOT_GOVERNED:{SOURCE}")
    if not v12r._meta_ok(SOURCE, src):
        raise RuntimeError("V14_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD")

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in v12r._iter_cached(SOURCE):
        bars = [dict(x) for x in packet.get("bars", [])]
        if bars:
            by_ticker[str(packet["ticker"])].append({"date": str(packet["date"]), "bars": bars})

    daily: dict[str, dict[str, Any]] = {}
    cohort: list[dict[str, Any]] = []
    open_low_final_total = 0

    for ticker, days in by_ticker.items():
        days.sort(key=lambda x: x["date"])
        for di in range(1, len(days)):
            day = days[di]
            prev_bars = days[di - 1]["bars"]
            bars = day["bars"]
            prev_closes = [float(b["close"]) for b in prev_bars if b.get("close") is not None]
            if not prev_closes:
                continue
            prev_close = prev_closes[-1]
            if prev_close <= 0:
                continue
            opens = [float(b["open"]) for b in bars if b.get("open") is not None]
            highs = [float(b["high"]) for b in bars if b.get("high") is not None]
            lows = [float(b["low"]) for b in bars if b.get("low") is not None]
            closes = [float(b["close"]) for b in bars if b.get("close") is not None]
            if not opens or not highs or not lows or not closes or max(highs) <= min(lows):
                continue
            op = opens[0]
            date = day["date"]
            d = daily.setdefault(date, {
                "date": date,
                "open_eq_low_final": [],
                "open_running_low_by_snapshot": defaultdict(list),
                "strong10_to12_success": [],
                "strong10_to12_failure": [],
            })

            open_eq_low_final = _eq(op, min(lows))
            if open_eq_low_final:
                d["open_eq_low_final"].append(ticker)
                open_low_final_total += 1

            run_low: float | None = None
            for i, bar in enumerate(bars):
                lo = bar.get("low")
                if lo is not None:
                    run_low = float(lo) if run_low is None else min(run_low, float(lo))
                if _is_publication_slot(bar.get("timestamp")) and run_low is not None and _eq(run_low, op):
                    d["open_running_low_by_snapshot"][str(bar.get("timestamp"))].append(ticker)

            touch: dict[float, int | None] = {
                rung: _first_touch(bars, prev_close * (1.0 + rung / 100.0)) for rung in UP_LADDER
            }
            idx10 = touch[10.0]
            if idx10 is None:
                continue
            comp = _strong_components(bars, idx10)
            if not comp.get("strong"):
                continue

            idx12 = touch[12.0]
            success = idx12 is not None and idx12 >= idx10
            run_low10 = min(float(b["low"]) for b in bars[:idx10 + 1] if b.get("low") is not None)
            pubs_after = [j for j in range(idx10 + 1, len(bars)) if _is_publication_slot(bars[j].get("timestamp"))]
            next_pub = pubs_after[0] if pubs_after else None
            retained = False
            if next_pub is not None and bars[next_pub].get("close") is not None:
                retained = _pct(float(bars[next_pub]["close"]), prev_close) >= 10.0

            def gap(a: float, b: float) -> int | None:
                ia, ib = touch[a], touch[b]
                return None if ia is None or ib is None or ib < ia else int(ib - ia)

            row = {
                "date": date,
                "ticker": ticker,
                "prev_close": prev_close,
                "open": op,
                "open_gap_pct_vs_prev_close": _pct(op, prev_close),
                "open_eq_low_final": open_eq_low_final,
                "open_running_low_at_10": _eq(run_low10, op),
                "cross_10_timestamp": _clock(bars[idx10]),
                "cross_10_close": bars[idx10].get("close"),
                "cross_10_close_chg_pct": _pct(float(bars[idx10]["close"]), prev_close) if bars[idx10].get("close") is not None else None,
                "hit_12": success,
                "hit_12_timestamp": _clock(bars[idx12]) if idx12 is not None else None,
                "retained_10_next_publication": retained,
                "bars_3_5_to_5": gap(3.5, 5.0),
                "bars_5_to_5_7": gap(5.0, 5.7),
                "bars_5_7_to_7": gap(5.7, 7.0),
                "bars_7_to_10": gap(7.0, 10.0),
                "eod_chg_pct": _pct(closes[-1], prev_close),
                "max_chg_pct": _pct(max(highs), prev_close),
                **{k: v for k, v in comp.items() if k != "strong"},
            }
            cohort.append(row)
            target = "strong10_to12_success" if success else "strong10_to12_failure"
            d[target].append(row)

    # Normalize defaultdict for JSON and attach daily summaries.
    days_out = []
    for date in sorted(daily):
        d = daily[date]
        snaps = {k: sorted(v) for k, v in sorted(d["open_running_low_by_snapshot"].items())}
        wins = d["strong10_to12_success"]
        fails = d["strong10_to12_failure"]
        days_out.append({
            "date": date,
            "open_eq_low_final_count": len(d["open_eq_low_final"]),
            "open_eq_low_final_tickers": sorted(d["open_eq_low_final"]),
            "open_running_low_by_snapshot": snaps,
            "strong10_count": len(wins) + len(fails),
            "hit12_count": len(wins),
            "fail12_count": len(fails),
            "hit12_rate": len(wins) / (len(wins) + len(fails)) if wins or fails else None,
            "strong10_to12_success": wins,
            "strong10_to12_failure": fails,
            "winner_profile": _summarize_group(wins),
            "failure_profile": _summarize_group(fails),
        })

    winners = [r for r in cohort if r["hit_12"]]
    failures = [r for r in cohort if not r["hit_12"]]
    return {
        "schema": "A1_TELEGRAM_MG_DAILY_STRENGTH_V14_RESULT_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "source": SOURCE,
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "cohort_definition": "FIRST_TOUCH_10PCT_VS_PREV_CLOSE_WITH_EXACT_PRICE_VALUE_STRONG_CROSS_DEFINITION_FROM_396_CASE_STUDY",
        "strong10_total": len(cohort),
        "strong10_hit12": len(winners),
        "strong10_fail12": len(failures),
        "strong10_hit12_rate": len(winners) / len(cohort) if cohort else None,
        "open_eq_low_final_total": open_low_final_total,
        "winner_profile": _summarize_group(winners),
        "failure_profile": _summarize_group(failures),
        "daily": days_out,
        "telegram_research_contract": {
            "daily_search_required": True,
            "open_low_live_field": "open_running_low_by_snapshot",
            "open_low_final_field": "open_eq_low_final_tickers",
            "note": "Final Open=Low is research/hindsight only. Telegram live eligibility must use Open=running-Low at the current snapshot.",
            "mg_columns_remain": ["CODE", "PRICE", "CHG%", "TP-1", "TP-2"],
        },
        "future_data_used_for_formula_state": False,
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
        "strong10_total": report["strong10_total"],
        "strong10_hit12": report["strong10_hit12"],
        "strong10_fail12": report["strong10_fail12"],
        "strong10_hit12_rate": report["strong10_hit12_rate"],
        "open_eq_low_final_total": report["open_eq_low_final_total"],
        "days": len(report["daily"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
