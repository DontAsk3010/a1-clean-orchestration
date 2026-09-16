from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_open_ladder_v13 import _eq, _pct
from .telegram_mg_replay import _is_publication_slot
from .telegram_openlow_strength_discovery_v16 import _effort_state, _formula_flags

SOURCE = "Raw Des 02-31-2024.csv"
FORMULA_ID = "OL_F_DEEP_PERSIST_NONDOWN_BOTH_FRESH"
ENTRY_MIN_CHG_PCT = 5.0
ENTRY_LATEST_TIME = "10:00"
ENTRY_BUDGET_IDR = 5_000_000.0
BUY_FEE_PCT = 0.15
SELL_FEE_PCT = 0.25


def _fmt_idr(v: float) -> str:
    sign = "-" if v < 0 else "+"
    x = f"{abs(v):,.0f}".replace(",", ".")
    return f"{sign}Rp{x}"


def _position(entry: float) -> tuple[int, int, float]:
    all_in_per_lot = entry * 100.0 * (1.0 + BUY_FEE_PCT / 100.0)
    lots = int(ENTRY_BUDGET_IDR // all_in_per_lot) if all_in_per_lot > 0 else 0
    shares = lots * 100
    buy_all_in = shares * entry * (1.0 + BUY_FEE_PCT / 100.0)
    return lots, shares, buy_all_in


def _net_pl(shares: int, buy_all_in: float, exit_price: float) -> float:
    return shares * exit_price * (1.0 - SELL_FEE_PCT / 100.0) - buy_all_in


def _state(bars: list[dict[str, Any]], i: int, op: float, run_low: float, run_high: float,
           last_pub_close: float | None, last_pub_run_high: float | None,
           openlow_streak: int, non_down_streak: int) -> tuple[dict[str, Any], int, int]:
    row = bars[i]
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
    s = {
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
    return s, openlow_streak, non_down_streak


def build_report(output_dir: str) -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    src = next(x for x in sources if str(x["source_name"]) == SOURCE)
    if not v12r._meta_ok(SOURCE, src):
        raise RuntimeError("V18_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD")

    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in v12r._iter_cached(SOURCE):
        bars = [dict(x) for x in packet.get("bars", [])]
        if bars:
            by_ticker[str(packet["ticker"])].append({"date": str(packet["date"]), "bars": bars})

    trades: list[dict[str, Any]] = []
    telegram: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))

    for ticker, days in by_ticker.items():
        days.sort(key=lambda x: x["date"])
        for di, day in enumerate(days):
            if di == 0:
                continue
            prev_closes = [float(b["close"]) for b in days[di-1]["bars"] if b.get("close") is not None]
            bars = day["bars"]
            opens = [float(b["open"]) for b in bars if b.get("open") is not None]
            if not prev_closes or prev_closes[-1] <= 0 or not opens:
                continue
            prev_close, op = prev_closes[-1], opens[0]
            dstr = day["date"]
            run_low = run_high = None
            last_pub_close = last_pub_run_high = None
            openlow_streak = non_down_streak = 0
            pos: dict[str, Any] | None = None
            episode_no = 0
            last_pub_i: int | None = None

            for i, row in enumerate(bars):
                lo, hi = row.get("low"), row.get("high")
                if lo is not None:
                    run_low = float(lo) if run_low is None else min(run_low, float(lo))
                if hi is not None:
                    run_high = float(hi) if run_high is None else max(run_high, float(hi))
                if not _is_publication_slot(row.get("timestamp")) or row.get("close") is None or run_low is None or run_high is None:
                    continue
                last_pub_i = i
                close = float(row["close"])
                ts = str(row.get("timestamp") or "")
                tm = ts[11:16] if len(ts) >= 16 else ts
                s, openlow_streak, non_down_streak = _state(
                    bars, i, op, run_low, run_high, last_pub_close, last_pub_run_high,
                    openlow_streak, non_down_streak,
                )
                active = bool(_formula_flags(s).get(FORMULA_ID, False))
                chg = _pct(close, prev_close)

                # A live position exits on the first publication where the formula is no longer valid.
                if pos is not None:
                    # High from this publication interval is attainable after the previous publication entry/update.
                    if row.get("high") is not None and float(row["high"]) > pos["max_price"]:
                        pos["max_price"] = float(row["high"])
                        pos["max_time"] = tm
                    if not active:
                        pos["exit_time"] = tm
                        pos["exit_price"] = close
                        pos["exit_reason"] = "OPEN_LOW_INVALIDATED"
                        pos["pl_realized_idr"] = _net_pl(pos["shares"], pos["buy_all_in"], close)
                        pos["pl_realized_pct"] = pos["pl_realized_idr"] / pos["buy_all_in"] * 100.0
                        pos["pl_max_idr"] = _net_pl(pos["shares"], pos["buy_all_in"], pos["max_price"])
                        pos["pl_max_pct"] = pos["pl_max_idr"] / pos["buy_all_in"] * 100.0
                        trades.append(pos)
                        pos = None

                # A new active episode after a completed exit is a new Rp5m entry.
                if pos is None and active and tm <= ENTRY_LATEST_TIME and chg >= ENTRY_MIN_CHG_PCT:
                    lots, shares, buy_all_in = _position(close)
                    if lots > 0:
                        episode_no += 1
                        pos = {
                            "date": dstr,
                            "ticker": ticker,
                            "episode": episode_no,
                            "entry_time": tm,
                            "entry_price": close,
                            "entry_chg_pct": chg,
                            "entry_budget_idr": ENTRY_BUDGET_IDR,
                            "lots": lots,
                            "shares": shares,
                            "buy_all_in": buy_all_in,
                            "max_price": close,
                            "max_time": tm,
                        }

                if pos is not None and active:
                    telegram[dstr][ts].append({
                        "ticker": ticker,
                        "episode": pos["episode"],
                        "status": "NEW" if tm == pos["entry_time"] else "UPDATE",
                        "price": close,
                        "chg_pct": chg,
                        "entry_time": pos["entry_time"],
                        "entry_price": pos["entry_price"],
                        "lots": pos["lots"],
                        "capital": pos["buy_all_in"],
                    })

                last_pub_close = close
                last_pub_run_high = run_high

            if pos is not None and last_pub_i is not None:
                row = bars[last_pub_i]
                close = float(row["close"])
                ts = str(row.get("timestamp") or "")
                tm = ts[11:16] if len(ts) >= 16 else ts
                pos["exit_time"] = tm
                pos["exit_price"] = close
                pos["exit_reason"] = "EOD"
                pos["pl_realized_idr"] = _net_pl(pos["shares"], pos["buy_all_in"], close)
                pos["pl_realized_pct"] = pos["pl_realized_idr"] / pos["buy_all_in"] * 100.0
                pos["pl_max_idr"] = _net_pl(pos["shares"], pos["buy_all_in"], pos["max_price"])
                pos["pl_max_pct"] = pos["pl_max_idr"] / pos["buy_all_in"] * 100.0
                trades.append(pos)

    trades.sort(key=lambda x: (x["date"], x["entry_time"], x["ticker"], x["episode"]))
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades: by_day[t["date"]].append(t)

    lines: list[str] = ["OPEN LOW | DECEMBER 2024 | REPLAY | CORE", "ENTRY BUDGET: Rp5.000.000 PER NEW SIGNAL/EPISODE", ""]
    for dstr in sorted(set(telegram) | set(by_day)):
        lines.append(f"===== {dstr} =====")
        for ts in sorted(telegram.get(dstr, {})):
            rows = sorted(telegram[dstr][ts], key=lambda x: (x["ticker"], x["episode"]))
            if not rows: continue
            tm = ts[11:16] if len(ts) >= 16 else ts
            lines.append(f"{tm} WIB")
            lines.append("STATUS | CODE | PRICE | CHG% | ENTRY | LOT | CAPITAL")
            for r in rows:
                lines.append(f"{r['status']} | {r['ticker']} | {r['price']:.4f} | {r['chg_pct']:+.2f}% | {r['entry_price']:.4f} | {r['lots']} | Rp{r['capital']:,.0f}".replace(",", "."))
        lines.append("DAILY TRADE RESULT")
        lines.append("CODE | ENTRY | EXIT | P/L REAL | MAX HIGH | P/L MAX | RESULT")
        for t in by_day.get(dstr, []):
            result = "WIN" if t["pl_realized_idr"] > 0 else ("BE" if abs(t["pl_realized_idr"]) < 1 else "FAIL")
            lines.append(
                f"{t['ticker']}#{t['episode']} | {t['entry_time']} @{t['entry_price']:.4f} | {t['exit_time']} @{t['exit_price']:.4f} [{t['exit_reason']}] | "
                f"{_fmt_idr(t['pl_realized_idr'])} ({t['pl_realized_pct']:+.2f}%) | {t['max_price']:.4f} @{t['max_time']} | "
                f"{_fmt_idr(t['pl_max_idr'])} ({t['pl_max_pct']:+.2f}%) | {result}"
            )
        lines.append("")

    total_real = sum(t["pl_realized_idr"] for t in trades)
    total_max = sum(t["pl_max_idr"] for t in trades)
    wins = sum(t["pl_realized_idr"] > 0 for t in trades)
    lines += ["===== DECEMBER SUMMARY =====", f"TRADES {len(trades)} | WIN {wins} | FAIL {len(trades)-wins} | P/L REAL {_fmt_idr(total_real)} | SUM P/L MAX {_fmt_idr(total_max)}"]

    report = {
        "schema": "A1_TELEGRAM_OPENLOW_TRADE_REPORT_V18",
        "source": SOURCE,
        "formula_id": FORMULA_ID,
        "entry_policy": "Rp5m per NEW SIGNAL/episode; repeats are UPDATE; re-entry allowed only after prior exit and a new valid episode",
        "exit_policy": "first 5-minute publication where OPEN LOW formula invalidates; otherwise EOD",
        "future_used_only_for_reconciliation_max_profit": True,
        "trades": trades,
        "summary": {"trades": len(trades), "wins": wins, "fails": len(trades)-wins, "pl_realized_idr": total_real, "pl_max_sum_idr": total_max},
    }
    (out / "OPEN_LOW_DEC_2024_TRADE_REPORT.txt").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (out / "OPEN_LOW_DEC_2024_TRADE_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return report


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--output-dir", required=True); a=p.parse_args(); build_report(a.output_dir); return 0

if __name__ == "__main__":
    raise SystemExit(main())
