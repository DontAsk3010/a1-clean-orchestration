from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_replay import _is_publication_slot

BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")
LADDERS = ((3.5, 5.0), (5.0, 5.7), (5.7, 12.0))
EPS = 1e-9


def _eq(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= EPS


def _pct(price: float, base: float) -> float:
    return (float(price) / float(base) - 1.0) * 100.0


def _rate(n: int, yes: int) -> float | None:
    return (yes / n) if n else None


def _summary(counter: Mapping[str, int]) -> dict[str, Any]:
    n = int(counter.get("n", 0))
    out = dict(counter)
    for key, value in list(counter.items()):
        if key == "n" or not key.endswith("_yes"):
            continue
        out[key.removesuffix("_yes") + "_rate"] = _rate(n, int(value))
    return out


def _strong(s: Mapping[str, Any]) -> bool:
    return bool(
        s.get("accept")
        and (
            s.get("value_wake")
            or s.get("volume_wake")
            or s.get("flow_wake")
            or s.get("accel")
        )
    )


def _assert_cache_ready(sources: Sequence[Mapping[str, Any]]) -> None:
    missing = [
        str(src["source_name"])
        for src in sources
        if not v12r._meta_ok(str(src["source_name"]), src)
    ]
    if missing:
        raise RuntimeError(f"V13_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD:{missing}")


def build_report(*, prior_days: int = 10) -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    _assert_cache_ready(sources)

    ex_post = {b: {"open_eq_low": defaultdict(int), "open_eq_high": defaultdict(int)} for b in BLOCKS}
    live = {b: {"open_eq_running_low": defaultdict(int), "open_eq_running_high": defaultdict(int)} for b in BLOCKS}
    ladders = {
        b: {
            f"{a:g}_to_{z:g}": {
                "cross": defaultdict(int),
                "hold": defaultdict(int),
                "strong": defaultdict(int),
                "open_eq_running_low_strong": defaultdict(int),
            }
            for a, z in LADDERS
        }
        for b in BLOCKS
    }
    counters = {b: {"ticker_days": 0, "publication_slots": 0} for b in BLOCKS}
    hist_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)

    for src in sources:
        source = str(src["source_name"])
        block = v11._block_for(source)
        for packet in v12r._iter_cached(source):
            bars = [dict(x) for x in packet.get("bars", [])]
            if not bars:
                continue
            ticker = str(packet["ticker"])
            counters[block]["ticker_days"] += 1

            o = bars[0].get("open")
            if o is None or float(o) <= 0:
                continue
            op = float(o)
            highs = [float(x["high"]) for x in bars if x.get("high") is not None]
            lows = [float(x["low"]) for x in bars if x.get("low") is not None]
            closes = [float(x["close"]) for x in bars if x.get("close") is not None]
            if not highs or not lows or not closes:
                continue
            day_hi = max(highs); day_lo = min(lows); final_close = closes[-1]

            if _eq(day_lo, op):
                c = ex_post[block]["open_eq_low"]
                c["n"] += 1
                if final_close > op: c["close_up_yes"] += 1
                if day_hi > op: c["ever_up_yes"] += 1
                if final_close >= op: c["close_nonnegative_yes"] += 1
            if _eq(day_hi, op):
                c = ex_post[block]["open_eq_high"]
                c["n"] += 1
                if final_close < op: c["close_down_yes"] += 1
                if day_lo < op: c["ever_down_yes"] += 1
                if final_close <= op: c["close_nonpositive_yes"] += 1

            cur = v11._prefix_series(bars)
            hp = hist_prefix[ticker][-prior_days:]
            pub = [i for i, row in enumerate(bars) if _is_publication_slot(row.get("timestamp"))]
            counters[block]["publication_slots"] += len(pub)

            run_hi = None; run_lo = None
            run_hi_by_i: dict[int, float] = {}; run_lo_by_i: dict[int, float] = {}
            for i, row in enumerate(bars):
                hi = row.get("high"); lo = row.get("low")
                if hi is not None: run_hi = float(hi) if run_hi is None else max(run_hi, float(hi))
                if lo is not None: run_lo = float(lo) if run_lo is None else min(run_lo, float(lo))
                if i in pub and run_hi is not None and run_lo is not None:
                    run_hi_by_i[i] = run_hi; run_lo_by_i[i] = run_lo

            # Live causal OPEN=running LOW/HIGH test: first non-opening publication snapshot only.
            for label, want_low in (("open_eq_running_low", True), ("open_eq_running_high", False)):
                first = None
                for i in pub:
                    if i == 0:
                        continue
                    extreme = run_lo_by_i.get(i) if want_low else run_hi_by_i.get(i)
                    if _eq(extreme, op):
                        first = i; break
                if first is not None:
                    row = bars[first]
                    close = row.get("close")
                    if close is not None:
                        c = live[block][label]
                        c["n"] += 1
                        future_hi = max(float(x["high"]) for x in bars[first:] if x.get("high") is not None)
                        future_lo = min(float(x["low"]) for x in bars[first:] if x.get("low") is not None)
                        if want_low:
                            if future_hi > float(close): c["future_up_from_signal_yes"] += 1
                            if final_close > op: c["close_up_vs_open_yes"] += 1
                            if day_lo >= op: c["open_low_survives_to_close_yes"] += 1
                        else:
                            if future_lo < float(close): c["future_down_from_signal_yes"] += 1
                            if final_close < op: c["close_down_vs_open_yes"] += 1
                            if day_hi <= op: c["open_high_survives_to_close_yes"] += 1

            # Ladder tests. "Strong" means cross survives one later publication snapshot and the
            # confirming snapshot has acceptance plus at least one pre-existing participation/accel state.
            for a, z in LADDERS:
                key = f"{a:g}_to_{z:g}"
                cross_i = None
                prev_path = None
                for i in pub:
                    close = bars[i].get("close")
                    if close is None: continue
                    path = _pct(float(close), op)
                    if path >= a and (prev_path is None or prev_path < a):
                        cross_i = i; break
                    prev_path = path
                if cross_i is None:
                    continue

                # Only evaluate a target that was not already achieved by the time of causal crossing.
                if _pct(run_hi_by_i.get(cross_i, day_hi), op) >= z:
                    continue
                future_after_cross = bars[cross_i + 1:]
                hit_after_cross = bool(future_after_cross) and max(
                    _pct(float(x["high"]), op) for x in future_after_cross if x.get("high") is not None
                ) >= z
                c = ladders[block][key]["cross"]
                c["n"] += 1
                if hit_after_cross: c["target_yes"] += 1

                next_pubs = [j for j in pub if j > cross_i]
                if not next_pubs:
                    continue
                confirm_i = next_pubs[0]
                confirm_close = bars[confirm_i].get("close")
                if confirm_close is None or _pct(float(confirm_close), op) < a:
                    continue
                if _pct(run_hi_by_i.get(confirm_i, day_hi), op) >= z:
                    continue
                future_after_confirm = bars[confirm_i + 1:]
                hit_after_confirm = bool(future_after_confirm) and max(
                    _pct(float(x["high"]), op) for x in future_after_confirm if x.get("high") is not None
                ) >= z
                c = ladders[block][key]["hold"]
                c["n"] += 1
                if hit_after_confirm: c["target_yes"] += 1

                if len(hp) < 3:
                    continue
                snap = v11._snapshot(cur, hp, confirm_i)
                if not snap or not _strong(snap):
                    continue
                c = ladders[block][key]["strong"]
                c["n"] += 1
                if hit_after_confirm: c["target_yes"] += 1

                if _eq(run_lo_by_i.get(confirm_i), op):
                    c = ladders[block][key]["open_eq_running_low_strong"]
                    c["n"] += 1
                    if hit_after_confirm: c["target_yes"] += 1

            hist_prefix[ticker].append(cur)
            hist_prefix[ticker] = hist_prefix[ticker][-prior_days:]

    out_expost = {
        b: {k: _summary(v) for k, v in groups.items()} for b, groups in ex_post.items()
    }
    out_live = {
        b: {k: _summary(v) for k, v in groups.items()} for b, groups in live.items()
    }
    out_ladders = {
        b: {
            key: {kind: _summary(counter) for kind, counter in kinds.items()}
            for key, kinds in group.items()
        }
        for b, group in ladders.items()
    }
    return {
        "schema": "A1_TELEGRAM_MG_OPEN_LADDER_V13_RESULT_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "governed_blocks": {
            "DISCOVERY": list(v11.DISCOVERY),
            "VALIDATION_A": list(v11.VALIDATION_A),
            "VALIDATION_B": list(v11.VALIDATION_B),
            "RESERVED_OOS_UNTOUCHED": v11.RESERVED_OOS,
        },
        "counters": counters,
        "definitions": {
            "ex_post_open_eq_low_high": "full-day extreme equality; descriptive only and NOT live-causal",
            "live_open_eq_running_low_high": "day open equals running extreme at first non-opening 5-minute publication snapshot where equality holds",
            "ladder_cross": "first 5-minute publication close crossing the supplied source level",
            "ladder_hold": "next publication close remains at/above source level",
            "ladder_strong": "hold plus existing V11 acceptance and at least one existing participation/acceleration state; no added numeric threshold",
            "target": "target level is first reached strictly after the causal cross/confirmation; cases where target was already reached are excluded",
        },
        "levels_pct": [3.5, 5.0, 5.7, 12.0],
        "ex_post_open_extreme": out_expost,
        "live_open_extreme": out_live,
        "continuation_ladders": out_ladders,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    a = p.parse_args()
    report = build_report(prior_days=a.prior_days)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
