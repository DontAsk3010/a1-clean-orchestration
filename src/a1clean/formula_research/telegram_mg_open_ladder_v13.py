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
    return yes / n if n else None


def _summary(counter: Mapping[str, int]) -> dict[str, Any]:
    n = int(counter.get("n", 0)); out = dict(counter)
    for k, v in counter.items():
        if k.endswith("_yes"):
            out[k[:-4] + "_rate"] = _rate(n, int(v))
    return out


def _assert_cache_ready(sources: Sequence[Mapping[str, Any]]) -> None:
    missing = [str(s["source_name"]) for s in sources if not v12r._meta_ok(str(s["source_name"]), s)]
    if missing:
        raise RuntimeError(f"V13_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD:{missing}")


def _five_vs_five_accel(bars: Sequence[Mapping[str, Any]], i: int) -> bool:
    if i < 9:
        return False
    last = bars[i-4:i+1]; prev = bars[i-9:i-4]
    def sm(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
        vals = [r.get(key) for r in rows]
        if any(v is None for v in vals):
            return None
        return sum(float(v) for v in vals)
    lv, pv = sm(last, "trade_value"), sm(prev, "trade_value")
    lq, pq = sm(last, "volume"), sm(prev, "volume")
    return bool((lv is not None and pv is not None and lv > pv) or (lq is not None and pq is not None and lq > pq))


def build_report(*, prior_days: int = 10) -> dict[str, Any]:
    del prior_days
    sources = v11._ordered_governed_sources()
    _assert_cache_ready(sources)
    ex_post = {b: {"open_eq_low": defaultdict(int), "open_eq_high": defaultdict(int)} for b in BLOCKS}
    live = {b: {"open_eq_running_low": defaultdict(int), "open_eq_running_high": defaultdict(int)} for b in BLOCKS}
    ladders = {b: {f"{a:g}_to_{z:g}": {k: defaultdict(int) for k in ("cross", "hold", "strong", "open_eq_running_low_strong")} for a, z in LADDERS} for b in BLOCKS}
    counters = {b: {"ticker_days": 0, "publication_slots": 0} for b in BLOCKS}

    for src in sources:
        source = str(src["source_name"]); block = v11._block_for(source)
        for packet in v12r._iter_cached(source):
            bars = packet.get("bars", [])
            if not bars: continue
            counters[block]["ticker_days"] += 1
            o = bars[0].get("open")
            if o is None or float(o) <= 0: continue
            op = float(o)
            highs = [float(x["high"]) for x in bars if x.get("high") is not None]
            lows = [float(x["low"]) for x in bars if x.get("low") is not None]
            closes = [float(x["close"]) for x in bars if x.get("close") is not None]
            if not highs or not lows or not closes: continue
            day_hi, day_lo, final_close = max(highs), min(lows), closes[-1]

            if _eq(day_lo, op):
                c = ex_post[block]["open_eq_low"]; c["n"] += 1
                if final_close > op: c["close_up_yes"] += 1
                if day_hi > op: c["ever_up_yes"] += 1
                if final_close >= op: c["close_nonnegative_yes"] += 1
            if _eq(day_hi, op):
                c = ex_post[block]["open_eq_high"]; c["n"] += 1
                if final_close < op: c["close_down_yes"] += 1
                if day_lo < op: c["ever_down_yes"] += 1
                if final_close <= op: c["close_nonpositive_yes"] += 1

            pub = []
            run_hi = run_lo = None
            for i, row in enumerate(bars):
                hi, lo = row.get("high"), row.get("low")
                if hi is not None: run_hi = float(hi) if run_hi is None else max(run_hi, float(hi))
                if lo is not None: run_lo = float(lo) if run_lo is None else min(run_lo, float(lo))
                if _is_publication_slot(row.get("timestamp")) and run_hi is not None and run_lo is not None and row.get("close") is not None:
                    pub.append({
                        "i": i, "close": float(row["close"]), "path": _pct(float(row["close"]), op),
                        "run_hi": run_hi, "run_lo": run_lo, "accel": _five_vs_five_accel(bars, i),
                    })
            counters[block]["publication_slots"] += len(pub)
            if not pub: continue

            for label, want_low in (("open_eq_running_low", True), ("open_eq_running_high", False)):
                first = next((p for p in pub[1:] if _eq(p["run_lo"] if want_low else p["run_hi"], op)), None)
                if first:
                    i = int(first["i"]); c = live[block][label]
                    c["n"] += 1
                    future_hi = max(float(x["high"]) for x in bars[i:] if x.get("high") is not None)
                    future_lo = min(float(x["low"]) for x in bars[i:] if x.get("low") is not None)
                    if want_low:
                        if future_hi > first["close"]: c["future_up_from_signal_yes"] += 1
                        if final_close > op: c["close_up_vs_open_yes"] += 1
                        if day_lo >= op: c["open_low_survives_to_close_yes"] += 1
                    else:
                        if future_lo < first["close"]: c["future_down_from_signal_yes"] += 1
                        if final_close < op: c["close_down_vs_open_yes"] += 1
                        if day_hi <= op: c["open_high_survives_to_close_yes"] += 1

            for a, z in LADDERS:
                key = f"{a:g}_to_{z:g}"; cross_pos = None
                for pos, p in enumerate(pub):
                    prev = pub[pos-1]["path"] if pos else None
                    if p["path"] >= a and (prev is None or prev < a): cross_pos = pos; break
                if cross_pos is None: continue
                cross = pub[cross_pos]
                if _pct(cross["run_hi"], op) >= z: continue
                future = bars[int(cross["i"])+1:]
                hit = bool(future) and max((_pct(float(x["high"]), op) for x in future if x.get("high") is not None), default=-999.0) >= z
                c = ladders[block][key]["cross"]; c["n"] += 1
                if hit: c["target_yes"] += 1

                if cross_pos + 1 >= len(pub): continue
                conf = pub[cross_pos+1]
                if conf["path"] < a or _pct(conf["run_hi"], op) >= z: continue
                future2 = bars[int(conf["i"])+1:]
                hit2 = bool(future2) and max((_pct(float(x["high"]), op) for x in future2 if x.get("high") is not None), default=-999.0) >= z
                c = ladders[block][key]["hold"]; c["n"] += 1
                if hit2: c["target_yes"] += 1

                # Strength is purely causal and adds no new numeric threshold:
                # level survives to next publication, price does not give back versus crossing close,
                # and 5-bar effort accelerates versus the immediately preceding 5 bars.
                if conf["close"] < cross["close"] or not conf["accel"]: continue
                c = ladders[block][key]["strong"]; c["n"] += 1
                if hit2: c["target_yes"] += 1
                if _eq(conf["run_lo"], op):
                    c = ladders[block][key]["open_eq_running_low_strong"]; c["n"] += 1
                    if hit2: c["target_yes"] += 1

    return {
        "schema": "A1_TELEGRAM_MG_OPEN_LADDER_V13_RESULT_V2",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "governed_blocks": {"DISCOVERY": list(v11.DISCOVERY), "VALIDATION_A": list(v11.VALIDATION_A), "VALIDATION_B": list(v11.VALIDATION_B), "RESERVED_OOS_UNTOUCHED": v11.RESERVED_OOS},
        "levels_pct": [3.5, 5.0, 5.7, 12.0],
        "definitions": {
            "ex_post_open_eq_low_high": "full-day equality; descriptive/hindsight only, never formula state",
            "live_open_eq_running_low_high": "open equals running low/high at a non-opening 5-minute publication snapshot",
            "cross": "first publication close crossing source level; target must not already have been reached",
            "hold": "next publication close remains at/above source level",
            "strong": "hold + confirming close >= crossing close + last-5 effort (trade value or volume) > previous-5 effort; no extra numeric threshold",
            "target": "target reached strictly after causal cross/confirmation",
        },
        "counters": counters,
        "ex_post_open_extreme": {b: {k: _summary(v) for k, v in g.items()} for b, g in ex_post.items()},
        "live_open_extreme": {b: {k: _summary(v) for k, v in g.items()} for b, g in live.items()},
        "continuation_ladders": {b: {key: {kind: _summary(c) for kind, c in kinds.items()} for key, kinds in g.items()} for b, g in ladders.items()},
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--output", required=True); p.add_argument("--prior-days", type=int, default=10); a = p.parse_args()
    Path(a.output).write_text(json.dumps(build_report(prior_days=a.prior_days), indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
