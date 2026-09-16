"""Open=Low pattern mining: sort, group, then let the boundaries fall out.

RESEARCH_ONLY. Lane: `research/claude-mg-discovery`.

--------------------------------------------------------------------------
WHY THIS REPLACES GUESS-THEN-TEST
--------------------------------------------------------------------------
Every candidate in this lane so far was a guess I then tested: pick a rule,
run it, keep or discard. `CLAUDE.md` explicitly warns against that shape --
"Do not collapse rich continuous data into a tiny boolean marker set too early.
Analyze continuous ratios/distributions first, then derive signatures only
after empirical separation is understood." The earlier entries did the opposite.

This module inverts the order. It does not propose a rule. It takes every
Open=Low scout signal, measures a continuous feature vector at signal time,
**sorts the population into buckets**, and reports where the outcome actually
concentrates. Boundaries are then read off the cells that recur AND separate --
they are an output, not an input.

--------------------------------------------------------------------------
WHAT IT PRODUCES
--------------------------------------------------------------------------
1. **Decile profile** per feature: the population split into ten ordered
   buckets, each with its support and P(reach target). This exposes the SHAPE
   of the relationship -- monotone, threshold-like, U-shaped or flat. A mean
   difference cannot tell these apart, which is why the earlier entries' mean
   contrast was a weak instrument.
2. **Cell mining** over 2-way and 3-way feature combinations: every cell with
   at least `min_support` signals, reported with support, P(reach target) and
   lift against the population base rate. A cell that both recurs and separates
   is the "pola berulang" the boundary should come from.
3. **Derived boundary proposal**: read from the highest-lift cells that clear
   the support floor, expressed as the feature ranges those cells occupy.

Nothing here is a validated filter. Cells are mined on one source; a cell that
survives only in-sample is noise wearing a pattern's clothes, and the module
reports support precisely so thin cells can be discounted on sight.

--------------------------------------------------------------------------
CAUSALITY
--------------------------------------------------------------------------
Every feature is measured at the signal bar from bars `0..t` plus prior-day
facts. The outcome label reads only bars after `t`, same trading date. Mining
happens on features and labels that were separated at collection time, so no
forward information can enter a feature by construction.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..pattern_discovery.source_reader import GovernedSourceReader
from ..google_drive import build_drive_api
from .formula_replay import packet_to_formula_bars
from .claude_mg_openlow_strength_v1 import (
    DEFAULT_CAPITAL_PER_SIGNAL,
    MIN_BARS,
    _day_frame,
    _forward_path,
    _hhmm,
    _position,
    _reject_oos_source,
    _signal_features,
    _slot_hhmm,
)

# Features mined. Price tier is included because IDX behaviour differs sharply
# across price bands and no earlier entry accounted for it.
FEATURES = (
    "chg_at_signal_pct",
    "bar_index",
    "prior_day_range_pct",
    "day_range_so_far_pct",
    "value_expansion",
    "close_location",
    "price",
    "prior_day_return_pct",
)


def _quantile_edges(values: Sequence[float], buckets: int) -> list[float]:
    ordered = sorted(values)
    if not ordered:
        return []
    edges = []
    for i in range(1, buckets):
        idx = min(len(ordered) - 1, max(0, int(round(i / buckets * (len(ordered) - 1)))))
        edges.append(ordered[idx])
    # Collapse duplicate edges so a spiky distribution does not create empty cells.
    out: list[float] = []
    for e in edges:
        if not out or e > out[-1]:
            out.append(e)
    return out


def _bucket_of(value: float | None, edges: Sequence[float]) -> int | None:
    if value is None:
        return None
    for i, edge in enumerate(edges):
        if value <= edge:
            return i
    return len(edges)


def _collect(
    source_name: str,
    *,
    min_chg_pct: float,
    strength_target_pct: float,
    capital: float = DEFAULT_CAPITAL_PER_SIGNAL,
) -> list[dict[str, Any]]:
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)

    per_ticker: dict[str, list[dict[str, Any]]] = {}
    for _row, packet in reader.iter_packets():
        frame = _day_frame(packet_to_formula_bars(packet)[0])
        if frame is not None:
            per_ticker.setdefault(str(packet.identity.ticker), []).append(frame)

    rows: list[dict[str, Any]] = []
    seen_ticker_days: set[tuple[str, str]] = set()
    for ticker, days in per_ticker.items():
        days.sort(key=lambda d: d["trading_date"])
        for i in range(1, len(days)):
            day, prev = days[i], days[i - 1]
            prev_close = prev["close"]
            if not prev_close or prev_close <= 0 or day["high"] <= day["low"]:
                continue
            prior_ret = None
            if i >= 2 and days[i - 2]["close"]:
                prior_ret = (prev_close / days[i - 2]["close"] - 1.0) * 100.0

            bars = day["bars"]
            low_so_far = None
            for t, bar in enumerate(bars):
                if bar.get("low") is not None:
                    lo = float(bar["low"])
                    low_so_far = lo if low_so_far is None else min(low_so_far, lo)
                if bar.get("close") is None or low_so_far is None or t < MIN_BARS - 1:
                    continue
                if low_so_far < day["open"]:
                    continue
                price = float(bar["close"])
                chg = (price / prev_close - 1.0) * 100.0
                if chg < min_chg_pct:
                    continue

                key = (ticker, day["trading_date"])
                first_for_ticker_day = key not in seen_ticker_days
                seen_ticker_days.add(key)
                feats = _signal_features(bars, t, prev["range_pct"])
                forward = bars[t + 1 :]
                highs = [float(b["high"]) for b in forward if b.get("high") is not None]
                max_after = max(highs) if highs else price
                path = _forward_path(price, forward)
                pos = _position(price, capital)
                shares = pos["shares"] if pos else 0.0
                rows.append(
                    {
                        "ticker": ticker,
                        "date": day["trading_date"],
                        "slot": _slot_hhmm(bar.get("timestamp")),
                        "first_detectable_time": _hhmm(bar.get("timestamp")),
                        "chg_at_signal_pct": chg,
                        "bar_index": float(feats["bar_index"]),
                        "prior_day_range_pct": feats["prior_day_range_pct"],
                        "day_range_so_far_pct": feats["day_range_so_far_pct"],
                        "value_expansion": feats["value_expansion"],
                        "close_location": feats["close_location"],
                        "price": price,
                        "prior_day_return_pct": prior_ret,
                        "reached_target": (max_after / prev_close - 1.0) * 100.0 >= strength_target_pct,
                        "max_chg_after_pct": (max_after / prev_close - 1.0) * 100.0,
                        # Outcome in rupiah, from the signal price, exiting at the
                        # same-day close. No target and no exit cleverness: a cell
                        # that is positive here is profitable on its own merits.
                        "eod_pct": path["eod_pct"],
                        "mfe_pct": path["mfe_pct"],
                        "mae_pct": path["mae_pct"],
                        "lots": pos["lots"] if pos else 0.0,
                        "cost_rp": pos["cost"] if pos else 0.0,
                        "pl_eod_rp": shares * (path["eod_price"] - price),
                        "max_profit_rp": shares * (path["best_price"] - price),
                        "tradeable": pos is not None,
                        # The feed republishes while a ticker still qualifies; the
                        # outcome study collapses to the first appearance so one
                        # opportunity cannot count as many. Same rows, two readings.
                        "first_for_ticker_day": first_for_ticker_day,
                    }
                )
    return rows


def _profile(rows: Sequence[Mapping[str, Any]], feature: str, buckets: int) -> dict[str, Any]:
    values = [r[feature] for r in rows if r.get(feature) is not None]
    if len(values) < buckets:
        return {"usable": False, "reason": "insufficient non-null values", "n": len(values)}
    edges = _quantile_edges(values, buckets)
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        b = _bucket_of(r.get(feature), edges)
        if b is not None:
            grouped[b].append(r)
    out = []
    for b in sorted(grouped):
        group = grouped[b]
        hit = sum(1 for r in group if r["reached_target"])
        vals = [r[feature] for r in group if r.get(feature) is not None]
        pls = [r["pl_eod_rp"] for r in group]
        out.append(
            {
                "bucket": b,
                "n": len(group),
                "range_low": min(vals) if vals else None,
                "range_high": max(vals) if vals else None,
                "p_reach_target": hit / len(group) if group else None,
                "mean_pl_rp": sum(pls) / len(pls) if pls else None,
                "total_pl_rp": sum(pls),
                "p_profitable": sum(1 for v in pls if v > 0) / len(pls) if pls else None,
            }
        )
    return {"usable": True, "edges": edges, "buckets": out}


def _mine_cells(
    rows: Sequence[Mapping[str, Any]],
    features: Sequence[str],
    *,
    buckets: int,
    min_support: int,
    max_combo: int,
) -> list[dict[str, Any]]:
    base_rate = sum(1 for r in rows if r["reached_target"]) / len(rows) if rows else 0.0
    base_mean_pl = sum(r["pl_eod_rp"] for r in rows) / len(rows) if rows else 0.0
    edge_map = {
        f: _quantile_edges([r[f] for r in rows if r.get(f) is not None], buckets) for f in features
    }

    cells: list[dict[str, Any]] = []
    for size in range(2, max_combo + 1):
        for combo in combinations(features, size):
            grouped: dict[tuple[int, ...], list[Mapping[str, Any]]] = defaultdict(list)
            for r in rows:
                key = tuple(_bucket_of(r.get(f), edge_map[f]) for f in combo)
                if any(k is None for k in key):
                    continue
                grouped[key].append(r)  # type: ignore[arg-type]
            for key, group in grouped.items():
                if len(group) < min_support:
                    continue
                hit = sum(1 for r in group if r["reached_target"])
                p = hit / len(group)
                pls = [r["pl_eod_rp"] for r in group]
                mean_pl = sum(pls) / len(pls)
                ranges = {}
                for f in combo:
                    vals = [r[f] for r in group if r.get(f) is not None]
                    ranges[f] = [min(vals), max(vals)] if vals else None
                cells.append(
                    {
                        "features": list(combo),
                        "support": len(group),
                        "p_reach_target": p,
                        "lift_pp": (p - base_rate) * 100.0,
                        "mean_pl_rp": mean_pl,
                        "total_pl_rp": sum(pls),
                        "p_profitable": sum(1 for v in pls if v > 0) / len(pls),
                        "mean_pl_lift_rp": mean_pl - base_mean_pl,
                        "mean_max_profit_rp": sum(r["max_profit_rp"] for r in group) / len(group),
                        "feature_ranges": ranges,
                    }
                )
    # Ranked by money per signal. Entry 016 established that a touch statistic
    # whose threshold overlaps the entry condition cannot fail, so ranking on
    # P(reach target) would rediscover the same illusion in cell form.
    cells.sort(key=lambda c: (c["mean_pl_rp"], c["support"]), reverse=True)
    return cells


def analyse(
    source_name: str,
    *,
    min_chg_pct: float,
    strength_target_pct: float,
    buckets: int,
    min_support: int,
    max_combo: int,
    top_cells: int,
    capital: float = DEFAULT_CAPITAL_PER_SIGNAL,
) -> dict[str, Any]:
    _reject_oos_source(source_name)
    rows = _collect(
        source_name,
        min_chg_pct=min_chg_pct,
        strength_target_pct=strength_target_pct,
        capital=capital,
    )
    if not rows:
        return {
            "schema": "A1_CLAUDE_OPENLOW_PATTERN_MINING_V1",
            "status": "RESEARCH_RESULT_NOT_CANONICAL",
            "source_name": source_name,
            "signals": 0,
            "note": "No Open=Low signals at this ignition floor -- nothing to mine.",
        }

    study = [r for r in rows if r["first_for_ticker_day"]]
    base_rate = sum(1 for r in study if r["reached_target"]) / len(study) if study else 0.0
    cells = _mine_cells(
        study, FEATURES, buckets=buckets, min_support=min_support, max_combo=max_combo
    )
    return {
        "schema": "A1_CLAUDE_OPENLOW_PATTERN_MINING_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "min_chg_pct": min_chg_pct,
        "strength_target_pct": strength_target_pct,
        "buckets": buckets,
        "min_support": min_support,
        "signals": len(study),
        "published_rows_all_bars": len(rows),
        "base_rate_p_reach_target": base_rate,
        "capital_per_signal": capital,
        "base_mean_pl_rp": (sum(r["pl_eod_rp"] for r in study) / len(study)) if study else None,
        "base_total_pl_rp": sum(r["pl_eod_rp"] for r in study),
        "decile_profiles": {f: _profile(study, f, buckets) for f in FEATURES},
        "top_cells": cells[:top_cells],
        "cells_meeting_support": len(cells),
        "signal_rows": rows,
        "outcome_is_evaluation_only_not_formula_input": True,
        "winner_only_filter_used": False,
    }


def _slot_grid(start: str, end: str, minutes: int) -> list[str]:
    def to_min(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)

    slots = []
    for t in range(to_min(start), to_min(end) + 1, minutes):
        slots.append(f"{t // 60:02d}:{t % 60:02d}")
    return slots


def render_screening_feed(
    payload: Mapping[str, Any], *, from_time: str = "09:00", slot_minutes: int = 5
) -> str:
    """Per day, every publication slot from 09:00 onward, screened or not.

    The owner's operational unit: evaluation runs on every 1-minute bar, but the
    feed reports on the 5-minute slot grid, and EVERY slot appears whether or not
    anything screened. Telegram Sub-Sub Master section 7 requires a valid
    zero-match to render its own symbol rather than vanish, so an empty slot can
    never be mistaken for an outage.
    """
    rows = payload.get("signal_rows") or []
    if not rows:
        return f"(no Open=Low signals for {payload.get('source_name')})"

    by_date: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_date[r["date"]][r["slot"]].append(r)

    lines = [
        f"OPEN=LOW SCREENING FEED — {payload.get('source_name')}",
        "RESEARCH RENDERING ONLY — NOT A TELEGRAM PUBLICATION.",
        f"evaluated on every 1-minute bar; published on the {slot_minutes}-minute slot grid",
        "",
    ]
    for date in sorted(by_date):
        slots_present = sorted(by_date[date])
        last = max(slots_present) if slots_present else from_time
        lines.append(f"===== {date} =====")
        for slot in _slot_grid(from_time, last, slot_minutes):
            hits = by_date[date].get(slot, [])
            if not hits:
                lines.append(f"[{slot}] ========")
                continue
            # One CODE per slot. A 5-minute slot contains five 1-minute bars, so
            # a ticker that still qualifies on each of them produced five identical
            # rows in the first run's feed. The Telegram contract publishes a
            # ticker once per snapshot, and the state that snapshot reports is the
            # LAST bar inside it, so later bars replace earlier ones.
            latest: dict[str, Mapping[str, Any]] = {}
            for h in hits:
                prior = latest.get(h["ticker"])
                if prior is None or h["first_detectable_time"] >= prior["first_detectable_time"]:
                    latest[h["ticker"]] = h
            body = "  ".join(
                f"{h['ticker']} {round(h['price']):,}".replace(",", ".") + f" {h['chg_at_signal_pct']:+.2f}%"
                for h in sorted(latest.values(), key=lambda x: x["ticker"])
            )
            lines.append(f"[{slot}] {body}")
        lines.append("")
    return "\n".join(lines)


def _rp(value: float) -> str:
    whole = int(round(abs(value)))
    body = f"{whole:,}".replace(",", ".")
    return f"-{body}" if value < 0 else body


def render(payload: Mapping[str, Any], *, top_cells: int) -> str:
    if not payload.get("signals"):
        return f"(no signals for {payload.get('source_name')} — nothing to mine)"
    base = payload["base_rate_p_reach_target"]
    target = payload["strength_target_pct"]
    cap = payload.get("capital_per_signal") or 0.0
    lines = [
        f"OPEN=LOW PATTERN MINING — {payload['source_name']}",
        f"signals={payload['signals']}  base P(reach {target:.0f}%)={base:.3f}  "
        f"cells meeting support={payload['cells_meeting_support']}",
        f"ENTRY Rp{_rp(cap)} per sinyal, keluar di close hari itu. "
        f"Base rata-rata P/L={_rp(payload.get('base_mean_pl_rp') or 0.0)}  "
        f"total={_rp(payload.get('base_total_pl_rp') or 0.0)}",
        "",
        "--- BENTUK TIAP FITUR (bucket desil, hasil dalam rupiah) ---",
    ]
    for feature, prof in payload["decile_profiles"].items():
        if not prof.get("usable"):
            lines.append(f"{feature}: UNUSABLE ({prof.get('reason')}, n={prof.get('n')})")
            continue
        lines.append(f"{feature}:")
        for b in prof["buckets"]:
            lines.append(
                f"  [{b['range_low']:>10.2f} .. {b['range_high']:>10.2f}]  n={b['n']:>5}  "
                f"untung={b['p_profitable']:.2f}  rata2 P/L={_rp(b['mean_pl_rp']):>12}  "
                f"total={_rp(b['total_pl_rp']):>14}"
            )
    lines.append("")
    lines.append(f"--- CELL BERULANG TERBAIK, diurut rata-rata rupiah (support >= {payload['min_support']}) ---")
    for c in payload["top_cells"][:top_cells]:
        spec = "  ".join(
            f"{f}=[{c['feature_ranges'][f][0]:.2f}..{c['feature_ranges'][f][1]:.2f}]"
            for f in c["features"]
            if c["feature_ranges"].get(f)
        )
        lines.append(
            f"n={c['support']:>4}  untung={c['p_profitable']:.3f}  "
            f"rata2 P/L={_rp(c['mean_pl_rp']):>12}  total={_rp(c['total_pl_rp']):>14}  "
            f"vs base={_rp(c['mean_pl_lift_rp']):>12}"
        )
        lines.append(f"        {spec}")
    return "\n".join(lines)


def _print_utf8(text: str) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-openlow-pattern-mining-v1")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--min-chg-pct", type=float, default=3.5)
    parser.add_argument("--strength-target-pct", type=float, default=10.0)
    parser.add_argument("--buckets", type=int, default=5)
    parser.add_argument("--min-support", type=int, default=25)
    parser.add_argument("--max-combo", type=int, default=3)
    parser.add_argument("--top-cells", type=int, default=40)
    parser.add_argument("--capital-per-signal", type=float, default=DEFAULT_CAPITAL_PER_SIGNAL)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-output", default=None)
    parser.add_argument("--feed-output", default=None)
    parser.add_argument("--from-time", default="09:00")
    parser.add_argument("--slot-minutes", type=int, default=5)
    args = parser.parse_args(argv)

    payload = analyse(
        args.source_name,
        min_chg_pct=args.min_chg_pct,
        strength_target_pct=args.strength_target_pct,
        capital=args.capital_per_signal,
        buckets=args.buckets,
        min_support=args.min_support,
        max_combo=args.max_combo,
        top_cells=args.top_cells,
    )
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.feed_output:
        Path(args.feed_output).write_text(
            render_screening_feed(payload, from_time=args.from_time, slot_minutes=args.slot_minutes)
            + "\n",
            encoding="utf-8",
        )
    text = render(payload, top_cells=args.top_cells)
    if args.report_output:
        Path(args.report_output).write_text(text + "\n", encoding="utf-8")
    _print_utf8(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
