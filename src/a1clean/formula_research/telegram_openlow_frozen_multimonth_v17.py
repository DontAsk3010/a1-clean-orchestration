from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date as _date
from pathlib import Path
from typing import Any, Mapping

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_open_ladder_v13 import _eq, _pct
from .telegram_mg_replay import _is_publication_slot
from .telegram_openlow_strength_discovery_v16 import _effort_state, _formula_flags

FORMULA_ID = "OL_F_DEEP_PERSIST_NONDOWN_BOTH_FRESH"
ENTRY_MIN_CHG_PCT = 5.0
ENTRY_LATEST_TIME = "10:00"
ENTRY_BUDGET_IDR = 5_000_000.0
BUY_FEE_PCT = 0.15
SELL_FEE_PCT = 0.25
TP1_FROM_PRICE_PCT = 5.0
TP2_FROM_PRICE_PCT = 10.0
MAX_CROSS_SOURCE_GAP_DAYS = 10


def _close_of_day(bars: list[dict[str, Any]]) -> float | None:
    vals = [float(x["close"]) for x in bars if x.get("close") is not None]
    return vals[-1] if vals else None


def _parse_date(s: str) -> _date:
    y, m, d = (int(x) for x in s.split("-"))
    return _date(y, m, d)


def _position(entry: float) -> tuple[int, int, float, float]:
    # Budget includes buy fee; 1 IDX lot = 100 shares.
    per_lot_all_in = entry * 100.0 * (1.0 + BUY_FEE_PCT / 100.0)
    lots = int(ENTRY_BUDGET_IDR // per_lot_all_in) if per_lot_all_in > 0 else 0
    shares = lots * 100
    gross = shares * entry
    all_in = gross * (1.0 + BUY_FEE_PCT / 100.0)
    return lots, shares, gross, all_in


def _net_pl(shares: int, buy_all_in: float, exit_price: float) -> float:
    proceeds = shares * exit_price * (1.0 - SELL_FEE_PCT / 100.0)
    return proceeds - buy_all_in


def _target(price: float, pct: float) -> float:
    return price * (1.0 + pct / 100.0)


def _evaluate_source(
    source_name: str,
    source_meta: Mapping[str, Any],
    prior_tail: dict[str, tuple[str, float]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, list[dict[str, Any]]]], dict[str, tuple[str, float]]]:
    if not v12r._meta_ok(source_name, source_meta):
        raise RuntimeError(f"V17_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD:{source_name}")

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in v12r._iter_cached(source_name):
        bars = [dict(x) for x in packet.get("bars", [])]
        if bars:
            by_ticker[str(packet["ticker"])].append({"date": str(packet["date"]), "bars": bars})

    entries: list[dict[str, Any]] = []
    telegram: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    new_tail = dict(prior_tail)

    for ticker, days in by_ticker.items():
        days.sort(key=lambda x: x["date"])
        prev_date: str | None = None
        prev_close: float | None = None
        if ticker in prior_tail:
            prev_date, prev_close = prior_tail[ticker]

        for day in days:
            dstr = day["date"]
            bars = day["bars"]
            op_vals = [float(x["open"]) for x in bars if x.get("open") is not None]
            day_close = _close_of_day(bars)
            if not op_vals or day_close is None:
                continue

            usable_prev = None
            if prev_date is not None and prev_close is not None:
                gap = (_parse_date(dstr) - _parse_date(prev_date)).days
                if 0 < gap <= MAX_CROSS_SOURCE_GAP_DAYS:
                    usable_prev = prev_close

            op = op_vals[0]
            if usable_prev is not None and usable_prev > 0:
                run_low = None
                run_high = None
                last_pub_close = None
                last_pub_run_high = None
                openlow_streak = 0
                non_down_streak = 0
                episode: dict[str, Any] | None = None

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
                    openlow_streak = openlow_streak + 1 if openlow else 0
                    rising = last_pub_close is not None and close >= last_pub_close
                    if last_pub_close is None:
                        non_down_streak = 1
                    elif rising:
                        non_down_streak += 1
                    else:
                        non_down_streak = 1
                    fresh_high = last_pub_run_high is not None and run_high > last_pub_run_high
                    bh, bl = row.get("high"), row.get("low")
                    acceptance = bool(bh is not None and bl is not None and close >= (float(bh) + float(bl)) / 2.0)
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
                    active = _formula_flags(state).get(FORMULA_ID, False)
                    ts = str(row.get("timestamp") or "")
                    tm = ts[11:16] if len(ts) >= 16 else ts
                    chg = _pct(close, usable_prev)

                    if not active:
                        episode = None
                    elif episode is None and tm <= ENTRY_LATEST_TIME and chg >= ENTRY_MIN_CHG_PCT:
                        lots, shares, gross, buy_all_in = _position(close)
                        if lots > 0:
                            future = bars[i + 1:]
                            future_high = max((float(x["high"]) for x in future if x.get("high") is not None), default=close)
                            eod_close = day_close
                            tp1_entry = _target(close, TP1_FROM_PRICE_PCT)
                            tp2_entry = _target(close, TP2_FROM_PRICE_PCT)
                            episode_id = f"{dstr}:{ticker}:{tm}"
                            episode = {
                                "episode_id": episode_id,
                                "source": source_name,
                                "date": dstr,
                                "ticker": ticker,
                                "entry_time": tm,
                                "entry_timestamp": ts,
                                "entry_price": close,
                                "entry_chg_pct": chg,
                                "entry_budget_idr": ENTRY_BUDGET_IDR,
                                "lots": lots,
                                "shares": shares,
                                "gross_entry_idr": gross,
                                "capital_used_idr": buy_all_in,
                                "cash_unused_idr": ENTRY_BUDGET_IDR - buy_all_in,
                                "entry_tp1": tp1_entry,
                                "entry_tp2": tp2_entry,
                                "tp1_hit": future_high >= tp1_entry,
                                "tp2_hit": future_high >= tp2_entry,
                                "future_high": future_high,
                                "max_future_pct_from_entry": (future_high / close - 1.0) * 100.0,
                                "net_max_pl_idr": _net_pl(shares, buy_all_in, future_high),
                                "eod_close": eod_close,
                                "net_eod_pl_idr": _net_pl(shares, buy_all_in, eod_close),
                                "state_at_entry": state,
                            }
                            entries.append(episode)

                    if active and episode is not None:
                        telegram[dstr][ts].append({
                            "episode_id": episode["episode_id"],
                            "ticker": ticker,
                            "time": tm,
                            "price": close,
                            "chg_pct": chg,
                            "tp1": _target(close, TP1_FROM_PRICE_PCT),
                            "tp2": _target(close, TP2_FROM_PRICE_PCT),
                            "entry_time": episode["entry_time"],
                            "entry_price": episode["entry_price"],
                            "is_new_entry": tm == episode["entry_time"],
                        })

                    last_pub_close = close
                    last_pub_run_high = run_high

            prev_date, prev_close = dstr, day_close
            new_tail[ticker] = (dstr, day_close)

    return entries, telegram, new_tail


def _monthly_key(dstr: str) -> str:
    return dstr[:7]


def _summarize_entries(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {
        "signals": n,
        "entry_budget_total_idr": n * ENTRY_BUDGET_IDR,
        "capital_used_total_idr": sum(float(x["capital_used_idr"]) for x in rows),
        "tp1_hit": sum(bool(x["tp1_hit"]) for x in rows),
        "tp2_hit": sum(bool(x["tp2_hit"]) for x in rows),
        "tp1_hit_rate": (sum(bool(x["tp1_hit"]) for x in rows) / n) if n else None,
        "tp2_hit_rate": (sum(bool(x["tp2_hit"]) for x in rows) / n) if n else None,
        "future_5pct_plus": sum(float(x["max_future_pct_from_entry"]) >= 5.0 for x in rows),
        "future_7pct_plus": sum(float(x["max_future_pct_from_entry"]) >= 7.0 for x in rows),
        "future_10pct_plus": sum(float(x["max_future_pct_from_entry"]) >= 10.0 for x in rows),
        "future_12pct_plus": sum(float(x["max_future_pct_from_entry"]) >= 12.0 for x in rows),
        "net_max_pl_total_idr": sum(float(x["net_max_pl_idr"]) for x in rows),
        "net_eod_pl_total_idr": sum(float(x["net_eod_pl_idr"]) for x in rows),
    }


def _fmt_idr(v: float) -> str:
    return f"Rp{v:,.0f}".replace(",", ".")


def _render_month(month: str, days: list[dict[str, Any]], entries: list[dict[str, Any]]) -> str:
    lines = [f"👀 MULAI GENIT — OPEN=LOW STRENGTH | {month} | REPLAY | CORE", ""]
    by_day_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        by_day_entries[e["date"]].append(e)
    for day in days:
        dstr = day["date"]
        lines.append(f"===== {dstr} =====")
        for snap in day["snapshots"]:
            if not snap["rows"]:
                continue
            lines.append(f"{snap['time']} WIB")
            lines.append("CODE | PRICE | CHG% | TP-1 | TP-2")
            for r in snap["rows"]:
                lines.append(f"{r['ticker']} | {r['price']:.4f} | {r['chg_pct']:+.2f}% | {r['tp1']:.4f} | {r['tp2']:.4f}")
        es = sorted(by_day_entries.get(dstr, []), key=lambda x: (x["entry_time"], x["ticker"]))
        sm = _summarize_entries(es)
        lines.append(f"DAILY: SIGNAL {sm['signals']} | TP1 {sm['tp1_hit']} | TP2 {sm['tp2_hit']} | NET MAX {_fmt_idr(sm['net_max_pl_total_idr'])} | EOD {_fmt_idr(sm['net_eod_pl_total_idr'])}")
        for e in es:
            result = "TP2" if e["tp2_hit"] else ("TP1" if e["tp1_hit"] else "FAIL")
            lines.append(
                f"{e['ticker']} | ENTRY {e['entry_time']} @ {e['entry_price']:.4f} | LOT {e['lots']} | CAPITAL {_fmt_idr(e['capital_used_idr'])} | HIGH {e['future_high']:.4f} | MAX {e['max_future_pct_from_entry']:+.2f}% | P/L MAX {_fmt_idr(e['net_max_pl_idr'])} | {result}"
            )
        lines.append("")
    ms = _summarize_entries(entries)
    lines.append("===== MONTHLY =====")
    lines.append(
        f"SIGNAL {ms['signals']} | TP1 {ms['tp1_hit']} ({(ms['tp1_hit_rate'] or 0)*100:.2f}%) | TP2 {ms['tp2_hit']} ({(ms['tp2_hit_rate'] or 0)*100:.2f}%) | >=7% {ms['future_7pct_plus']} | >=10% {ms['future_10pct_plus']} | >=12% {ms['future_12pct_plus']}"
    )
    lines.append(f"TOTAL ENTRY BUDGET {_fmt_idr(ms['entry_budget_total_idr'])} | NET MAX {_fmt_idr(ms['net_max_pl_total_idr'])} | EOD {_fmt_idr(ms['net_eod_pl_total_idr'])}")
    return "\n".join(lines) + "\n"


def build_report(output_dir: str) -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    prior_tail: dict[str, tuple[str, float]] = {}
    all_entries: list[dict[str, Any]] = []
    tg_all: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    for src in sources:
        name = str(src["source_name"])
        entries, tg, prior_tail = _evaluate_source(name, src, prior_tail)
        all_entries.extend(entries)
        for dstr, snaps in tg.items():
            for ts, rows in snaps.items():
                tg_all[dstr][ts].extend(rows)

    days = []
    for dstr in sorted(tg_all):
        snaps = []
        for ts in sorted(tg_all[dstr]):
            rows = sorted(tg_all[dstr][ts], key=lambda x: x["ticker"])
            snaps.append({"timestamp": ts, "time": ts[11:16] if len(ts) >= 16 else ts, "rows": rows})
        days.append({"date": dstr, "snapshots": snaps})

    monthly_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    monthly_days: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in all_entries:
        monthly_entries[_monthly_key(e["date"])].append(e)
    for d in days:
        monthly_days[_monthly_key(d["date"])].append(d)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    month_summaries = {}
    for month in sorted(monthly_days):
        es = sorted(monthly_entries.get(month, []), key=lambda x: (x["date"], x["entry_time"], x["ticker"]))
        text = _render_month(month, monthly_days[month], es)
        (out / f"telegram-openlow-{month}.txt").write_text(text, encoding="utf-8")
        month_summaries[month] = _summarize_entries(es)

    report = {
        "schema": "A1_TELEGRAM_OPENLOW_FROZEN_MULTIMONTH_V17_RESULT_V1",
        "mode": "REPLAY",
        "formula_id": "OL_G_FROZEN_HIGH_PROGRESS",
        "formula": "OL_F_DEEP_PERSIST_NONDOWN_BOTH_FRESH + CURRENT_CHG>=5% + FIRST_ENTRY_NOT_LATER_THAN_10:00",
        "frozen_from": "DECEMBER_2024_ONLY",
        "telegram_repeat_policy": "REPEAT_EVERY_5MIN_WHILE_OL_F_ACTIVE; REPEATS_ARE_STATUS_UPDATES_NOT_NEW_RP5M_ENTRIES",
        "position_policy": {"budget_per_new_episode_idr": ENTRY_BUDGET_IDR, "buy_fee_pct": BUY_FEE_PCT, "sell_fee_pct": SELL_FEE_PCT, "lot_size_shares": 100},
        "target_policy": {"dynamic_per_snapshot_tp1_from_current_price_pct": TP1_FROM_PRICE_PCT, "dynamic_per_snapshot_tp2_from_current_price_pct": TP2_FROM_PRICE_PCT, "entry_reconciliation_uses_entry_snapshot_targets": True},
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "reserved_march_2025_oos_touched": False,
        "month_summaries": month_summaries,
        "overall": _summarize_entries(all_entries),
        "entries": sorted(all_entries, key=lambda x: (x["date"], x["entry_time"], x["ticker"])),
        "days": days,
    }
    (out / "telegram-openlow-v17-result.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    summary_lines = ["OPEN=LOW V17 MULTI-MONTH SUMMARY"]
    for m in sorted(month_summaries):
        s = month_summaries[m]
        summary_lines.append(f"{m} | SIGNAL {s['signals']} | TP1 {s['tp1_hit']} | TP2 {s['tp2_hit']} | >=10% {s['future_10pct_plus']} | >=12% {s['future_12pct_plus']} | NET MAX {_fmt_idr(s['net_max_pl_total_idr'])} | EOD {_fmt_idr(s['net_eod_pl_total_idr'])}")
    (out / "telegram-openlow-v17-summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--output-dir", required=True); a = p.parse_args()
    r = build_report(a.output_dir)
    print(json.dumps({"months": r["month_summaries"], "overall": r["overall"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
