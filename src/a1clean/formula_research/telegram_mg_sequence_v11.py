from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict
from .telegram_mg_multihypothesis_v8e import _prefix_series
from .telegram_mg_replay import _is_publication_slot
from . import telegram_mg_question_driven_v10 as v10

DISCOVERY = (
    "Raw Des 02-31-2024.csv",
    "Raw Jan 01-31-2025.csv",
    "Raw Feb 03-28-2025.csv",
    "Raw April 01-30-2025.csv",
    "Raw Mei 01-30-2025.csv",
    "Raw Juni 02-30-2025.csv",
    "Raw Juli 01-31-2025.csv",
    "Raw Agust 01-29-2025.csv",
    "Raw Sep 01-30-2025.csv",
    "Raw Oct 01-31-2025.csv",
)
VALIDATION_A = (
    "Raw Nov 03-29-2025.csv",
    "Raw Des 01-31-2025.csv",
    "Raw Jan 01-30-2026.csv",
)
VALIDATION_B = (
    "Raw Feb 02-27-2026.csv",
    "Raw Mar 02-31-2026.csv",
    "Raw Apr 01-30-2026.csv",
    "Raw Mei 01-29-2026.csv",
)
RESERVED_OOS = "Raw Maret 03-31-2025.csv"
BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")

FORMULAS = (
    "J01_QUIET_MONEY_WAKE_RESPONSE_RETENTION",
    "J02_SHAKEOUT_FLOW_RECLAIM_HOLD",
    "J03_FLOW_LEADS_DELAYED_PRICE_RESPONSE",
    "J04_EFFORT_RESPONSE_FLIP",
    "J05_HIGHER_LOW_COMPRESSION_EXPANSION",
    "J06_RISE_PULLBACK_BASE_REACCELERATION",
    "J07_SELL_EXHAUSTION_BUY_TURN",
    "J08_TWO_WAVE_RELOAD",
)


def _med(xs: Sequence[float | None]) -> float | None:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    m = n // 2
    return vals[m] if n % 2 else (vals[m - 1] + vals[m]) / 2.0


def _gt(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and float(a) > float(b)


def _ordered_governed_sources() -> list[dict[str, Any]]:
    found = {str(x["source_name"]): dict(x) for x in _discover_sources_strict()}
    wanted = list(DISCOVERY + VALIDATION_A + VALIDATION_B)
    missing = [x for x in wanted if x not in found]
    if missing:
        raise ValueError(f"V11_MISSING_GOVERNED_SOURCES:{missing}")
    if RESERVED_OOS in wanted:
        raise AssertionError("RESERVED_OOS_MUST_NOT_BE_IN_GOVERNED_RUN")
    return [found[x] for x in wanted]


def _block_for(source: str) -> str:
    if source in DISCOVERY:
        return "DISCOVERY"
    if source in VALIDATION_A:
        return "VALIDATION_A"
    if source in VALIDATION_B:
        return "VALIDATION_B"
    raise ValueError(f"UNEXPECTED_SOURCE:{source}")


def _preconditions(history: Sequence[v10.DayBehavior]) -> set[str]:
    if len(history) < 6:
        return set()
    prev3 = list(history[-6:-3])
    last3 = list(history[-3:])
    last5 = list(history[-5:])
    last6 = list(history[-6:])
    out: set[str] = set()

    prev_range = _med([x.range_pct for x in prev3])
    last_range = _med([x.range_pct for x in last3])
    prev_value = _med([x.value for x in prev3])
    last_value = _med([x.value for x in last3])
    prev_volume = _med([x.volume for x in prev3])
    last_volume = _med([x.volume for x in last3])
    prev_abs_ret = _med([abs(x.ret_pct) for x in prev3])
    last_abs_ret = _med([abs(x.ret_pct) for x in last3])
    prev_nbss = _med([x.nbss for x in prev3])
    last_nbss = _med([x.nbss for x in last3])
    prev_pos = _med([x.positive_nbss_bar_fraction for x in prev3])
    last_pos = _med([x.positive_nbss_bar_fraction for x in last3])
    prev_sellres = _med([x.sell_pressure_resilience_fraction for x in prev3])
    last_sellres = _med([x.sell_pressure_resilience_fraction for x in last3])
    prev_loc = _med([x.close_location for x in prev3])
    last_loc = _med([x.close_location for x in last3])
    last_ret = _med([x.ret_pct for x in last3])

    contracts = prev_range is not None and last_range is not None and last_range < prev_range
    value_build = prev_value is not None and last_value is not None and last_value > prev_value
    volume_build = prev_volume is not None and last_volume is not None and last_volume > prev_volume
    contained = prev_abs_ret is not None and last_abs_ret is not None and last_abs_ret <= prev_abs_ret
    nbss_improves = prev_nbss is not None and last_nbss is not None and last_nbss > prev_nbss
    pos_improves = prev_pos is not None and last_pos is not None and last_pos > prev_pos
    sellres_improves = prev_sellres is not None and last_sellres is not None and last_sellres > prev_sellres
    loc_improves = prev_loc is not None and last_loc is not None and last_loc > prev_loc

    if contracts and value_build and contained:
        out.add("J01_QUIET_MONEY_WAKE_RESPONSE_RETENTION")

    if min(x.low for x in last3) < min(x.low for x in prev3) and loc_improves and (nbss_improves or pos_improves):
        out.add("J02_SHAKEOUT_FLOW_RECLAIM_HOLD")

    positive_nbss_days = sum(1 for x in last5 if x.nbss is not None and x.nbss > 0)
    no_breakout = last5[-1].high <= max(x.high for x in last5[:-1])
    if positive_nbss_days >= 3 and no_breakout:
        out.add("J03_FLOW_LEADS_DELAYED_PRICE_RESPONSE")

    if (value_build or volume_build) and contained:
        out.add("J04_EFFORT_RESPONSE_FLIP")

    lows3 = [x.low for x in last3]
    if lows3[0] <= lows3[1] <= lows3[2] and contracts:
        out.add("J05_HIGHER_LOW_COMPRESSION_EXPANSION")

    closes6 = [x.close for x in last6]
    peak = max(closes6)
    peak_i = closes6.index(peak)
    prior_rise = peak > closes6[0] and peak_i > 0
    pulled_back = peak_i < len(closes6) - 1 and closes6[-1] < peak
    if prior_rise and pulled_back and contracts:
        out.add("J06_RISE_PULLBACK_BASE_REACCELERATION")

    if (last_ret is not None and last_ret <= 0) and sellres_improves and lows3[0] <= lows3[1] <= lows3[2]:
        out.add("J07_SELL_EXHAUSTION_BUY_TURN")

    # J08 is current-day sequence led. It only requires enough prior same-clock baseline.
    out.add("J08_TWO_WAVE_RELOAD")
    return out


def _hist_med(history_prefix: Sequence[Sequence[Mapping[str, float | None]]], index: int, key: str) -> float | None:
    vals = [
        float(s[index][key])
        for s in history_prefix
        if index < len(s) and s[index] and s[index].get(key) is not None
    ]
    return _med(vals)


def _snapshot(
    current: Sequence[Mapping[str, float | None]],
    history_prefix: Sequence[Sequence[Mapping[str, float | None]]],
    index: int,
) -> dict[str, Any]:
    if index >= len(current) or not current[index]:
        return {}
    cur = current[index]
    hv = _hist_med(history_prefix, index, "cur_value")
    hvol = _hist_med(history_prefix, index, "cur_volume")
    hflow = _hist_med(history_prefix, index, "cur_nbss_to_value")
    hpath = _hist_med(history_prefix, index, "cur_path_pct")
    hrange = _hist_med(history_prefix, index, "cur_range_pct")
    hloc = _hist_med(history_prefix, index, "cur_close_location")
    hvacc = _hist_med(history_prefix, index, "cur_value_accel_5v5")
    hvolacc = _hist_med(history_prefix, index, "cur_volume_accel_5v5")
    path = cur.get("cur_path_pct")
    return {
        "value_wake": _gt(cur.get("cur_value"), hv),
        "volume_wake": _gt(cur.get("cur_volume"), hvol),
        "flow_wake": _gt(cur.get("cur_nbss_to_value"), hflow),
        "path_up": _gt(path, hpath),
        "range_expand": _gt(cur.get("cur_range_pct"), hrange),
        "accept": _gt(cur.get("cur_close_location"), hloc),
        "accel": _gt(cur.get("cur_value_accel_5v5"), hvacc) or _gt(cur.get("cur_volume_accel_5v5"), hvolacc),
        "path": None if path is None else float(path),
        "close_location": cur.get("cur_close_location"),
        "nbss_to_value": cur.get("cur_nbss_to_value"),
        "value_ratio": (float(cur["cur_value"]) / hv) if cur.get("cur_value") is not None and hv not in (None, 0) else None,
        "volume_ratio": (float(cur["cur_volume"]) / hvol) if cur.get("cur_volume") is not None and hvol not in (None, 0) else None,
    }


def _wake(fid: str, s: Mapping[str, Any]) -> bool:
    if fid == "J01_QUIET_MONEY_WAKE_RESPONSE_RETENTION":
        return bool(s["value_wake"] and s["volume_wake"])
    if fid == "J02_SHAKEOUT_FLOW_RECLAIM_HOLD":
        return bool(s["value_wake"] and (s["flow_wake"] or s["volume_wake"]))
    if fid == "J03_FLOW_LEADS_DELAYED_PRICE_RESPONSE":
        return bool(s["flow_wake"] and s["value_wake"])
    if fid == "J04_EFFORT_RESPONSE_FLIP":
        return bool(s["value_wake"] or s["volume_wake"])
    if fid == "J05_HIGHER_LOW_COMPRESSION_EXPANSION":
        return bool(s["value_wake"] and s["volume_wake"])
    if fid == "J06_RISE_PULLBACK_BASE_REACCELERATION":
        return bool(s["value_wake"] and s["volume_wake"])
    if fid == "J07_SELL_EXHAUSTION_BUY_TURN":
        return bool(s["flow_wake"] and s["value_wake"])
    if fid == "J08_TWO_WAVE_RELOAD":
        return bool(s["value_wake"] and s["volume_wake"] and s["path_up"])
    return False


def _response(fid: str, s: Mapping[str, Any]) -> bool:
    if fid == "J03_FLOW_LEADS_DELAYED_PRICE_RESPONSE":
        return bool(s["path_up"] and s["accept"])
    if fid == "J05_HIGHER_LOW_COMPRESSION_EXPANSION":
        return bool(s["range_expand"] and s["path_up"] and s["accept"])
    if fid == "J07_SELL_EXHAUSTION_BUY_TURN":
        return bool(s["path_up"] and s["accept"] and (s["flow_wake"] or s["value_wake"]))
    if fid == "J08_TWO_WAVE_RELOAD":
        return bool(s["path_up"] and s["accept"])
    return bool(s["accel"] and s["path_up"] and s["accept"])


def _retention(fid: str, s: Mapping[str, Any], wake_path: float | None, response_path: float | None) -> bool:
    path = s.get("path")
    if path is None:
        return False
    baseline_hold = bool(s["path_up"] and s["accept"])
    if wake_path is not None and float(path) < float(wake_path):
        return False
    if fid == "J03_FLOW_LEADS_DELAYED_PRICE_RESPONSE":
        return baseline_hold and bool(s["flow_wake"] or s["value_wake"])
    if fid == "J05_HIGHER_LOW_COMPRESSION_EXPANSION":
        return baseline_hold and bool(s["value_wake"] or s["volume_wake"])
    if fid == "J07_SELL_EXHAUSTION_BUY_TURN":
        return baseline_hold and bool(s["flow_wake"] or s["value_wake"])
    if fid == "J08_TWO_WAVE_RELOAD":
        return baseline_hold and bool(s["accel"]) and response_path is not None and float(path) > float(response_path)
    return baseline_hold and bool(s["value_wake"] or s["volume_wake"])


def _q(xs: Sequence[float], q: float) -> float | None:
    vals = sorted(float(x) for x in xs if math.isfinite(float(x)))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    p = (len(vals) - 1) * q
    lo = int(math.floor(p)); hi = int(math.ceil(p)); w = p - lo
    return vals[lo] if lo == hi else vals[lo] * (1.0 - w) + vals[hi] * w


def _metric(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    mfe = [x[0] for x in rows]; mae = [x[1] for x in rows]; eod = [x[2] for x in rows]
    return {
        "n": len(rows),
        "positive_net_mfe_count": sum(x > 0 for x in mfe),
        "positive_net_mfe_rate": (sum(x > 0 for x in mfe) / len(mfe)) if mfe else None,
        "q10_net_mfe_pct": _q(mfe, 0.10),
        "q25_net_mfe_pct": _q(mfe, 0.25),
        "median_net_mfe_pct": _q(mfe, 0.50),
        "q75_net_mfe_pct": _q(mfe, 0.75),
        "q90_net_mfe_pct": _q(mfe, 0.90),
        "median_mae_pct": _q(mae, 0.50),
        "median_eod_net_pct": _q(eod, 0.50),
    }


def _strict(metrics: Mapping[str, Mapping[str, Any]], min_support: int) -> bool:
    for block in BLOCKS:
        m = metrics[block]
        if int(m["n"]) < min_support:
            return False
        if m["q25_net_mfe_pct"] is None or float(m["q25_net_mfe_pct"]) <= 0:
            return False
        if m["median_net_mfe_pct"] is None or float(m["median_net_mfe_pct"]) <= 0:
            return False
    return True


def build_report(*, prior_days: int = 10, buy_fee: float = 0.15, sell_fee: float = 0.25, min_support: int = 40) -> dict[str, Any]:
    sources = _ordered_governed_sources()
    results: dict[str, dict[str, list[tuple[float, float, float]]]] = {
        b: defaultdict(list) for b in BLOCKS
    }
    examples: dict[str, dict[str, list[dict[str, Any]]]] = {
        b: defaultdict(list) for b in BLOCKS
    }
    counters = {b: {"ticker_days": 0, "publication_slots": 0, "signals": 0} for b in BLOCKS}
    hist_day: dict[str, list[v10.DayBehavior]] = defaultdict(list)
    hist_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)
    api = build_drive_api(read_write=False)

    for src in sources:
        source = str(src["source_name"])
        block = _block_for(source)
        reader = GovernedSourceReader(api, source_name=source)
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(x) for x in all_bars if x.get("session_eligible")]
            if not bars:
                continue
            counters[block]["ticker_days"] += 1
            ticker = str(packet.identity.ticker)
            date = str(packet.identity.trading_date)
            hd = hist_day[ticker][-prior_days:]
            hp = hist_prefix[ticker][-prior_days:]
            cur = _prefix_series(bars)
            pres = _preconditions(hd)
            hi, lo, final_close = v10._suffix(bars)
            states: dict[str, dict[str, Any]] = {
                fid: {"stage": 0, "wake_index": None, "wake_path": None, "response_index": None, "response_path": None}
                for fid in FORMULAS
                if fid in pres
            }
            seen: set[str] = set()

            if states and len(hp) >= 3:
                for i, row in enumerate(bars):
                    if not _is_publication_slot(row.get("timestamp")):
                        continue
                    counters[block]["publication_slots"] += 1
                    snap = _snapshot(cur, hp, i)
                    if not snap:
                        continue
                    for fid, st in states.items():
                        if fid in seen:
                            continue
                        stage = int(st["stage"])
                        if stage == 0:
                            if _wake(fid, snap):
                                st["stage"] = 1
                                st["wake_index"] = i
                                st["wake_path"] = snap.get("path")
                            continue
                        if stage == 1:
                            if i <= int(st["wake_index"]):
                                continue
                            if _response(fid, snap):
                                st["stage"] = 2
                                st["response_index"] = i
                                st["response_path"] = snap.get("path")
                            elif not (snap["value_wake"] or snap["volume_wake"] or snap["flow_wake"] or snap["path_up"]):
                                st.update({"stage": 0, "wake_index": None, "wake_path": None, "response_index": None, "response_path": None})
                            continue
                        if stage == 2:
                            if i <= int(st["response_index"]):
                                continue
                            if _retention(fid, snap, st.get("wake_path"), st.get("response_path")):
                                oc = v10._outcome(bars, i, hi, lo, final_close, buy_fee, sell_fee)
                                if oc is not None:
                                    results[block][fid].append(oc)
                                    counters[block]["signals"] += 1
                                    if len(examples[block][fid]) < 5:
                                        close = row.get("close")
                                        examples[block][fid].append({
                                            "source": source,
                                            "ticker": ticker,
                                            "date": date,
                                            "timestamp": row.get("timestamp"),
                                            "signal_close": close,
                                            "path_pct": snap.get("path"),
                                            "value_ratio": snap.get("value_ratio"),
                                            "volume_ratio": snap.get("volume_ratio"),
                                            "nbss_to_value": snap.get("nbss_to_value"),
                                            "net_mfe_pct": oc[0],
                                            "mae_pct": oc[1],
                                            "eod_net_pct": oc[2],
                                        })
                                    seen.add(fid)
                            elif not snap["path_up"]:
                                st.update({"stage": 0, "wake_index": None, "wake_path": None, "response_index": None, "response_path": None})

            d = v10._day_behavior(bars, date)
            if d is not None:
                hist_day[ticker].append(d)
                hist_day[ticker] = hist_day[ticker][-prior_days:]
                hist_prefix[ticker].append(cur)
                hist_prefix[ticker] = hist_prefix[ticker][-prior_days:]

    formulas: list[dict[str, Any]] = []
    for fid in FORMULAS:
        metrics = {b: _metric(results[b].get(fid, [])) for b in BLOCKS}
        strict = _strict(metrics, min_support)
        worst_q25 = min(
            float(metrics[b]["q25_net_mfe_pct"] if metrics[b]["q25_net_mfe_pct"] is not None else -999.0)
            for b in BLOCKS
        )
        worst_median = min(
            float(metrics[b]["median_net_mfe_pct"] if metrics[b]["median_net_mfe_pct"] is not None else -999.0)
            for b in BLOCKS
        )
        formulas.append({
            "id": fid,
            "strict_cross_period_pass": strict,
            "worst_block_q25_net_mfe_pct": worst_q25,
            "worst_block_median_net_mfe_pct": worst_median,
            "metrics": metrics,
            "examples": {b: examples[b].get(fid, []) for b in BLOCKS},
        })
    formulas.sort(
        key=lambda r: (
            bool(r["strict_cross_period_pass"]),
            float(r["worst_block_q25_net_mfe_pct"]),
            float(r["worst_block_median_net_mfe_pct"]),
        ),
        reverse=True,
    )
    strict_rows = [x for x in formulas if x["strict_cross_period_pass"]]
    return {
        "schema": "A1_TELEGRAM_MG_SEQUENCE_V11_RESULT_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "method": "ORDERED_PRECONDITION_WAKE_RESPONSE_ACCEPTANCE_RETENTION_FIRST_CAUSAL_SIGNAL_PER_FORMULA_PER_TICKER_DAY",
        "formula_count": len(FORMULAS),
        "formulas_tested": list(FORMULAS),
        "governed_blocks": {
            "DISCOVERY": list(DISCOVERY),
            "VALIDATION_A": list(VALIDATION_A),
            "VALIDATION_B": list(VALIDATION_B),
            "RESERVED_OOS_UNTOUCHED": RESERVED_OOS,
        },
        "execution": {"buy_fee_pct": buy_fee, "sell_fee_pct": sell_fee},
        "min_support": min_support,
        "counters": counters,
        "strict_survivor_count": len(strict_rows),
        "strict_survivors": strict_rows,
        "ranked_formulas": formulas,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "same_snapshot_coexistence_is_not_sequence": True,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
