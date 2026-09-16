from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_open_ladder_v13 import _eq, _pct
from .telegram_mg_replay import _is_publication_slot

SOURCE = "Raw Des 02-31-2024.csv"
OUTCOME_LEVELS = (3.0, 5.0, 7.0, 10.0, 12.0)


def _sum_window(bars: Sequence[Mapping[str, Any]], start: int, end: int, key: str) -> float | None:
    vals = [bars[i].get(key) for i in range(start, end)]
    if not vals or any(v is None for v in vals):
        return None
    return sum(float(v) for v in vals)


def _effort_state(bars: Sequence[Mapping[str, Any]], i: int) -> tuple[bool | None, bool | None, float | None, float | None]:
    if i < 9:
        return None, None, None, None
    tv_now = _sum_window(bars, i - 4, i + 1, "trade_value")
    tv_prev = _sum_window(bars, i - 9, i - 4, "trade_value")
    vol_now = _sum_window(bars, i - 4, i + 1, "volume")
    vol_prev = _sum_window(bars, i - 9, i - 4, "volume")
    tv_acc = None if tv_now is None or tv_prev is None else tv_now > tv_prev
    vol_acc = None if vol_now is None or vol_prev is None else vol_now > vol_prev
    tv_ratio = None if tv_now is None or tv_prev in (None, 0.0) else tv_now / tv_prev
    vol_ratio = None if vol_now is None or vol_prev in (None, 0.0) else vol_now / vol_prev
    return tv_acc, vol_acc, tv_ratio, vol_ratio


def _q(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    pos = p * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def _summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    fut = [float(r["max_future_pct_from_signal"]) for r in rows]
    return {
        "n": len(rows),
        "positive_rate": (sum(v > 0 for v in fut) / len(fut)) if fut else None,
        "q25_future_pct": _q(fut, 0.25),
        "median_future_pct": _q(fut, 0.50),
        "q75_future_pct": _q(fut, 0.75),
        "q90_future_pct": _q(fut, 0.90),
        **{f"hit_{level:g}_pct_rate": (sum(v >= level for v in fut) / len(fut)) if fut else None for level in OUTCOME_LEVELS},
    }


def _formula_flags(s: Mapping[str, Any]) -> dict[str, bool]:
    # No optimized return threshold is used in executable state. These are causal structure families.
    openlow = bool(s["openlow"])
    rising = bool(s["rising"])
    acceptance = bool(s["acceptance"])
    fresh_high = bool(s["fresh_running_high"])
    tv = s["trade_value_accel"] is True
    vol = s["volume_accel"] is True
    persist2 = int(s["openlow_streak"]) >= 2
    persist3 = int(s["openlow_streak"]) >= 3
    nondown3 = int(s["non_down_streak"]) >= 3
    return {
        "OL_A_PERSIST_RISE_EFFORT": openlow and persist2 and rising and (tv or vol),
        "OL_B_PERSIST_RISE_BOTH_EFFORT": openlow and persist2 and rising and tv and vol,
        "OL_C_PERSIST_FRESH_HIGH_EFFORT": openlow and persist2 and rising and fresh_high and (tv or vol),
        "OL_D_PERSIST_FRESH_HIGH_BOTH_ACCEPT": openlow and persist2 and rising and fresh_high and tv and vol and acceptance,
        "OL_E_DEEP_PERSIST_NONDOWN_EFFORT": openlow and persist3 and nondown3 and (tv or vol),
        "OL_F_DEEP_PERSIST_NONDOWN_BOTH_FRESH": openlow and persist3 and nondown3 and tv and vol and fresh_high,
    }


def build_report() -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    src = next((x for x in sources if str(x["source_name"]) == SOURCE), None)
    if src is None or not v12r._meta_ok(SOURCE, src):
        raise RuntimeError("V16_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD")

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in v12r._iter_cached(SOURCE):
        bars = [dict(x) for x in packet.get("bars", [])]
        if bars:
            by_ticker[str(packet["ticker"])].append({"date": str(packet["date"]), "bars": bars})

    formula_first: dict[str, list[dict[str, Any]]] = defaultdict(list)
    telegram: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    feature_rows: list[dict[str, Any]] = []

    for ticker, days in by_ticker.items():
        days.sort(key=lambda x: x["date"])
        for di, day in enumerate(days):
            if di == 0:
                continue
            bars = day["bars"]
            date = day["date"]
            prev_closes = [float(b["close"]) for b in days[di - 1]["bars"] if b.get("close") is not None]
            opens = [float(b["open"]) for b in bars if b.get("open") is not None]
            if not prev_closes or prev_closes[-1] <= 0 or not opens:
                continue
            prev_close = prev_closes[-1]
            op = opens[0]
            run_low = None
            run_high = None
            last_pub_close = None
            last_pub_run_high = None
            openlow_streak = 0
            non_down_streak = 0
            seen_formula: set[str] = set()

            for i, row in enumerate(bars):
                lo, hi = row.get("low"), row.get("high")
                if lo is not None:
                    run_low = float(lo) if run_low is None else min(run_low, float(lo))
                if hi is not None:
                    run_high = float(hi) if run_high is None else max(run_high, float(hi))
                if not _is_publication_slot(row.get("timestamp")) or row.get("close") is None or run_low is None or run_high is None:
                    continue
                close = float(row["close"])
                openlow = _eq(run_low, op)
                if openlow:
                    openlow_streak += 1
                else:
                    openlow_streak = 0
                rising = last_pub_close is not None and close >= last_pub_close
                if last_pub_close is None:
                    non_down_streak = 1
                elif rising:
                    non_down_streak += 1
                else:
                    non_down_streak = 1
                fresh_high = last_pub_run_high is not None and run_high > last_pub_run_high
                bar_high = row.get("high")
                bar_low = row.get("low")
                acceptance = False
                if bar_high is not None and bar_low is not None:
                    acceptance = close >= (float(bar_high) + float(bar_low)) / 2.0
                tv_acc, vol_acc, tv_ratio, vol_ratio = _effort_state(bars, i)
                state = {
                    "openlow": openlow,
                    "openlow_streak": openlow_streak,
                    "non_down_streak": non_down_streak,
                    "rising": rising,
                    "fresh_running_high": fresh_high,
                    "acceptance": acceptance,
                    "trade_value_accel": tv_acc,
                    "volume_accel": vol_acc,
                    "trade_value_ratio": tv_ratio,
                    "volume_ratio": vol_ratio,
                }
                flags = _formula_flags(state)
                future = bars[i + 1:]
                future_high = max((float(b["high"]) for b in future if b.get("high") is not None), default=close)
                future_pct = (future_high / close - 1.0) * 100.0
                chg_pct = _pct(close, prev_close)
                ts = str(row.get("timestamp") or "")
                base = {
                    "date": date,
                    "ticker": ticker,
                    "timestamp": ts,
                    "time": ts[11:16] if len(ts) >= 16 else ts,
                    "price": close,
                    "chg_pct": chg_pct,
                    "max_future_pct_from_signal": future_pct,
                    **state,
                }
                if openlow:
                    feature_rows.append(base)
                for fid, active in flags.items():
                    if not active:
                        continue
                    telegram[date][ts].append({**base, "formula_id": fid})
                    if fid not in seen_formula:
                        seen_formula.add(fid)
                        formula_first[fid].append(base)
                last_pub_close = close
                last_pub_run_high = run_high

    feature_contrast: dict[str, Any] = {}
    for feature in ("rising", "fresh_running_high", "acceptance", "trade_value_accel", "volume_accel"):
        yes = [r for r in feature_rows if r.get(feature) is True]
        no = [r for r in feature_rows if r.get(feature) is False]
        feature_contrast[feature] = {"true": _summary(yes), "false": _summary(no)}
    for streak in (2, 3, 4):
        yes = [r for r in feature_rows if int(r.get("openlow_streak") or 0) >= streak]
        no = [r for r in feature_rows if int(r.get("openlow_streak") or 0) < streak]
        feature_contrast[f"openlow_streak_ge_{streak}"] = {"true": _summary(yes), "false": _summary(no)}

    telegram_days = []
    for date in sorted(telegram):
        snaps = []
        for ts in sorted(telegram[date]):
            rows = sorted(telegram[date][ts], key=lambda r: (r["ticker"], r["formula_id"]))
            snaps.append({"timestamp": ts, "time": ts[11:16] if len(ts) >= 16 else ts, "rows": rows})
        telegram_days.append({"date": date, "snapshots": snaps})

    return {
        "schema": "A1_TELEGRAM_OPENLOW_STRENGTH_DISCOVERY_V16_RESULT_V1",
        "mode": "REPLAY",
        "source": SOURCE,
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "formula_definitions": {
            "OL_A_PERSIST_RISE_EFFORT": "OPENLOW + persists 2 publications + non-giveback + trade-value OR volume acceleration",
            "OL_B_PERSIST_RISE_BOTH_EFFORT": "A + both trade-value and volume acceleration",
            "OL_C_PERSIST_FRESH_HIGH_EFFORT": "A + fresh running high",
            "OL_D_PERSIST_FRESH_HIGH_BOTH_ACCEPT": "C + both effort accelerations + bar acceptance",
            "OL_E_DEEP_PERSIST_NONDOWN_EFFORT": "OPENLOW persists 3 publications + 3-publication non-down path + effort acceleration",
            "OL_F_DEEP_PERSIST_NONDOWN_BOTH_FRESH": "E + both effort accelerations + fresh running high",
        },
        "first_signal_formula_metrics": {fid: _summary(rows) for fid, rows in sorted(formula_first.items())},
        "feature_contrast_all_openlow_snapshots": feature_contrast,
        "telegram_policy": "REPEAT_EVERY_5MIN_WHILE_OPENLOW_FORMULA_REMAINS_ACTIVE",
        "telegram_days": telegram_days,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--output", required=True); a = p.parse_args()
    report = build_report()
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["first_signal_formula_metrics"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
