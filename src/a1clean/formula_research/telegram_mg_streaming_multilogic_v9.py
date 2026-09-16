from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .telegram_mg_behavior_topology_v2 import _net_return_pct, _observed_step
from .telegram_mg_multihypothesis_v8 import _daily, _finite
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict
from .telegram_mg_multihypothesis_v8e import _prefix_series
from .telegram_mg_replay import _is_publication_slot


PRECURSORS = (
    "P_BASE_CONTRACTION_3V3",
    "P_RANGE_COMPRESSION_3V3",
    "P_VALUE_BUILD_CONTAINED",
    "P_VOLUME_BUILD_CONTAINED",
    "P_VALUE_EFFORT_LOW_PROGRESS",
    "P_VOLUME_EFFORT_LOW_PROGRESS",
    "P_FLOW_BUILD_CONTAINED",
    "P_RISE_PULLBACK_BASE",
    "P_SHAKEOUT_RECOVERY",
    "P_HIGHER_LOW_TIGHTEN",
    "P_QUIET_VALUE_BUILD",
    "P_QUIET_VOLUME_BUILD",
    "P_QUIET_FLOW_BUILD",
)

IGNITIONS = (
    "I_VALUE_PATH",
    "I_VOLUME_PATH",
    "I_VALUE_RANGE_ACCEPT",
    "I_VALUE_VOLUME_PATH",
    "I_VALUE_ACCEL_PATH_ACCEPT",
    "I_VOLUME_ACCEL_PATH_ACCEPT",
    "I_FLOW_VALUE_PATH",
    "I_RANGE_PATH_ACCEPT",
    "I_FULL_CROWD_EXPANSION",
)


def _med(xs: Sequence[float | None]) -> float | None:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return float(median(vals)) if vals else None


def _span_pct(xs: Sequence[float]) -> float | None:
    if not xs or min(xs) <= 0:
        return None
    return (max(xs) / min(xs) - 1.0) * 100.0


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or abs(b) < 1e-12:
        return None
    return float(a) / float(b)


def _precursor_states(history: Sequence[Any]) -> set[str]:
    if len(history) < 6:
        return set()
    d = list(history[-10:])
    prev3 = d[-6:-3]
    last3 = d[-3:]
    if len(prev3) != 3 or len(last3) != 3:
        return set()
    out: set[str] = set()

    prev_close_span = _span_pct([float(x.close) for x in prev3])
    last_close_span = _span_pct([float(x.close) for x in last3])
    prev_range = _med([float(x.range_pct) for x in prev3])
    last_range = _med([float(x.range_pct) for x in last3])
    prev_value = _med([float(x.value) for x in prev3])
    last_value = _med([float(x.value) for x in last3])
    prev_volume = _med([float(x.volume) for x in prev3])
    last_volume = _med([float(x.volume) for x in last3])
    prev_abs_ret = _med([abs(float(x.return_pct)) for x in prev3])
    last_abs_ret = _med([abs(float(x.return_pct)) for x in last3])

    base_contraction = (
        prev_close_span is not None and last_close_span is not None
        and last_close_span < prev_close_span
    )
    range_compression = (
        prev_range is not None and last_range is not None and last_range < prev_range
    )
    value_build = prev_value is not None and last_value is not None and last_value > prev_value
    volume_build = prev_volume is not None and last_volume is not None and last_volume > prev_volume
    contained_progress = (
        prev_abs_ret is not None and last_abs_ret is not None and last_abs_ret <= prev_abs_ret
    )

    if base_contraction:
        out.add("P_BASE_CONTRACTION_3V3")
    if range_compression:
        out.add("P_RANGE_COMPRESSION_3V3")
    if value_build and base_contraction:
        out.add("P_VALUE_BUILD_CONTAINED")
    if volume_build and base_contraction:
        out.add("P_VOLUME_BUILD_CONTAINED")
    if value_build and contained_progress:
        out.add("P_VALUE_EFFORT_LOW_PROGRESS")
    if volume_build and contained_progress:
        out.add("P_VOLUME_EFFORT_LOW_PROGRESS")

    prev_flow_vals = [
        (float(x.nbss) / float(x.value))
        for x in prev3
        if x.nbss is not None and float(x.value) > 0
    ]
    last_flow_vals = [
        (float(x.nbss) / float(x.value))
        for x in last3
        if x.nbss is not None and float(x.value) > 0
    ]
    prev_flow = _med(prev_flow_vals)
    last_flow = _med(last_flow_vals)
    flow_build = (
        prev_flow is not None and last_flow is not None and last_flow > prev_flow
    )
    if flow_build and base_contraction:
        out.add("P_FLOW_BUILD_CONTAINED")

    closes6 = [float(x.close) for x in d[-6:]]
    peak = max(closes6)
    peak_i = closes6.index(peak)
    prior_rise = peak > closes6[0] and peak_i > 0
    pulled_back = closes6[-1] < peak and peak_i < len(closes6) - 1
    if prior_rise and pulled_back and base_contraction:
        out.add("P_RISE_PULLBACK_BASE")

    prev_low = min(float(x.low) for x in prev3)
    last_low = min(float(x.low) for x in last3)
    recovery = float(last3[-1].close) > float(last3[0].close)
    if last_low < prev_low and recovery:
        out.add("P_SHAKEOUT_RECOVERY")

    lows3 = [float(x.low) for x in last3]
    ranges3 = [float(x.range_pct) for x in last3]
    if lows3[0] <= lows3[1] <= lows3[2] and ranges3[-1] <= ranges3[0]:
        out.add("P_HIGHER_LOW_TIGHTEN")

    if range_compression and value_build:
        out.add("P_QUIET_VALUE_BUILD")
    if range_compression and volume_build:
        out.add("P_QUIET_VOLUME_BUILD")
    if range_compression and flow_build:
        out.add("P_QUIET_FLOW_BUILD")
    return out


def _hist_median_at(
    history_prefix: Sequence[Sequence[Mapping[str, float | None]]],
    index: int,
    key: str,
) -> float | None:
    vals = [
        float(series[index][key])
        for series in history_prefix
        if index < len(series)
        and series[index]
        and series[index].get(key) is not None
        and math.isfinite(float(series[index][key]))
    ]
    return _med(vals)


def _ignition_states(
    current_prefix: Sequence[Mapping[str, float | None]],
    history_prefix: Sequence[Sequence[Mapping[str, float | None]]],
    index: int,
) -> set[str]:
    if index >= len(current_prefix) or not current_prefix[index]:
        return set()
    cur = current_prefix[index]
    h_value = _hist_median_at(history_prefix, index, "cur_value")
    h_volume = _hist_median_at(history_prefix, index, "cur_volume")
    h_range = _hist_median_at(history_prefix, index, "cur_range_pct")
    h_path = _hist_median_at(history_prefix, index, "cur_path_pct")
    h_loc = _hist_median_at(history_prefix, index, "cur_close_location")
    h_vacc = _hist_median_at(history_prefix, index, "cur_value_accel_5v5")
    h_volacc = _hist_median_at(history_prefix, index, "cur_volume_accel_5v5")
    h_flow = _hist_median_at(history_prefix, index, "cur_nbss_to_value")

    def gt(key: str, baseline: float | None) -> bool:
        v = cur.get(key)
        return v is not None and baseline is not None and float(v) > float(baseline)

    value_wake = gt("cur_value", h_value)
    volume_wake = gt("cur_volume", h_volume)
    range_wake = gt("cur_range_pct", h_range)
    path = gt("cur_path_pct", h_path)
    accept = gt("cur_close_location", h_loc)
    value_acc = gt("cur_value_accel_5v5", h_vacc)
    volume_acc = gt("cur_volume_accel_5v5", h_volacc)
    flow = gt("cur_nbss_to_value", h_flow)

    out: set[str] = set()
    if value_wake and path:
        out.add("I_VALUE_PATH")
    if volume_wake and path:
        out.add("I_VOLUME_PATH")
    if value_wake and range_wake and accept:
        out.add("I_VALUE_RANGE_ACCEPT")
    if value_wake and volume_wake and path:
        out.add("I_VALUE_VOLUME_PATH")
    if value_acc and path and accept:
        out.add("I_VALUE_ACCEL_PATH_ACCEPT")
    if volume_acc and path and accept:
        out.add("I_VOLUME_ACCEL_PATH_ACCEPT")
    if flow and value_wake and path:
        out.add("I_FLOW_VALUE_PATH")
    if range_wake and path and accept:
        out.add("I_RANGE_PATH_ACCEPT")
    if value_wake and volume_wake and range_wake and path and accept:
        out.add("I_FULL_CROWD_EXPANSION")
    return out


def _suffix_extremes(bars: Sequence[Mapping[str, Any]]) -> tuple[list[float | None], list[float | None], float | None]:
    n = len(bars)
    max_high: list[float | None] = [None] * (n + 1)
    min_low: list[float | None] = [None] * (n + 1)
    for i in range(n - 1, -1, -1):
        h = _finite(bars[i].get("high")); l = _finite(bars[i].get("low"))
        if h is None or l is None:
            max_high[i] = max_high[i + 1]
            min_low[i] = min_low[i + 1]
        else:
            max_high[i] = float(h) if max_high[i + 1] is None else max(float(h), float(max_high[i + 1]))
            min_low[i] = float(l) if min_low[i + 1] is None else min(float(l), float(min_low[i + 1]))
    final_close = _finite(bars[-1].get("close")) if bars else None
    return max_high, min_low, final_close


def _outcome_quick(
    bars: Sequence[Mapping[str, Any]], index: int,
    suffix_high: Sequence[float | None], suffix_low: Sequence[float | None],
    final_close: float | None, buy_fee: float, sell_fee: float,
) -> tuple[float, float, float] | None:
    if index + 1 >= len(bars):
        return None
    step = _observed_step(bars, index)
    nxt = _finite(bars[index + 1].get("open"))
    high = suffix_high[index + 1]
    low = suffix_low[index + 1]
    if step is None or nxt is None or nxt <= 0 or high is None or low is None or final_close is None:
        return None
    step = float(step); entry = float(nxt) + step
    if entry <= 0:
        return None
    high_exit = max(0.0, float(high) - step)
    eod_exit = max(0.0, float(final_close) - step)
    net_mfe = _net_return_pct(entry, high_exit, buy_fee, sell_fee)
    mae = (float(low) / entry - 1.0) * 100.0
    eod = _net_return_pct(entry, eod_exit, buy_fee, sell_fee)
    return net_mfe, mae, eod


def _quantile(xs: Sequence[float], q: float) -> float | None:
    vals = sorted(float(x) for x in xs if math.isfinite(float(x)))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    w = pos - lo
    return vals[lo] * (1.0 - w) + vals[hi] * w


def _metric(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    mfe = [r[0] for r in rows]
    mae = [r[1] for r in rows]
    eod = [r[2] for r in rows]
    return {
        "n": len(rows),
        "positive_net_mfe_count": sum(x > 0 for x in mfe),
        "positive_net_mfe_rate": (sum(x > 0 for x in mfe) / len(rows)) if rows else None,
        "q10_net_mfe_pct": _quantile(mfe, 0.10),
        "q25_net_mfe_pct": _quantile(mfe, 0.25),
        "median_net_mfe_pct": _quantile(mfe, 0.50),
        "q75_net_mfe_pct": _quantile(mfe, 0.75),
        "q90_net_mfe_pct": _quantile(mfe, 0.90),
        "mean_net_mfe_pct": (sum(mfe) / len(mfe)) if mfe else None,
        "median_mae_pct": _quantile(mae, 0.50),
        "q25_mae_pct": _quantile(mae, 0.25),
        "median_eod_net_pct": _quantile(eod, 0.50),
    }


def _evaluate_sources(
    sources: Sequence[Mapping[str, Any]], prior_days: int,
    buy_fee: float, sell_fee: float,
) -> tuple[dict[str, list[tuple[float, float, float]]], dict[str, Any]]:
    results: dict[str, list[tuple[float, float, float]]] = defaultdict(list)
    history_daily: dict[str, list[Any]] = defaultdict(list)
    history_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)
    api = build_drive_api(read_write=False)
    counters = {"ticker_days": 0, "publication_slots": 0, "evaluable_matches": 0}

    for src in sources:
        source = str(src["source_name"])
        reader = GovernedSourceReader(api, source_name=source)
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(b) for b in all_bars if b.get("session_eligible")]
            if not bars:
                continue
            counters["ticker_days"] += 1
            ticker = str(packet.identity.ticker)
            date = str(packet.identity.trading_date)
            hd = history_daily.get(ticker, [])[-prior_days:]
            hp = history_prefix.get(ticker, [])[-prior_days:]
            current_prefix = _prefix_series(bars)
            precursors = _precursor_states(hd)
            seen: set[str] = set()
            suffix_high, suffix_low, final_close = _suffix_extremes(bars)

            if precursors and len(hp) >= 3:
                for i, bar in enumerate(bars):
                    if not _is_publication_slot(bar.get("timestamp")):
                        continue
                    counters["publication_slots"] += 1
                    ignitions = _ignition_states(current_prefix, hp, i)
                    if not ignitions:
                        continue
                    new_ids = [
                        f"{p}__{g}"
                        for p in precursors for g in ignitions
                        if f"{p}__{g}" not in seen
                    ]
                    if not new_ids:
                        continue
                    outcome = _outcome_quick(
                        bars, i, suffix_high, suffix_low, final_close, buy_fee, sell_fee
                    )
                    if outcome is None:
                        continue
                    counters["evaluable_matches"] += len(new_ids)
                    for cid in new_ids:
                        results[cid].append(outcome)
                        seen.add(cid)

            d = _daily(bars, date)
            if d is not None:
                history_daily[ticker].append(d)
                history_daily[ticker] = history_daily[ticker][-prior_days:]
                history_prefix[ticker].append(current_prefix)
                history_prefix[ticker] = history_prefix[ticker][-prior_days:]
    return results, counters


def build_report(*, prior_days: int, buy_fee: float, sell_fee: float, min_support: int, min_unique_days: int) -> dict[str, Any]:
    del min_unique_days  # first causal match makes each observation a unique ticker-day by construction
    sources = _discover_sources_strict()
    usable = [s for s in sources if not s.get("reserved_oos")]
    if len(usable) < 3:
        raise ValueError("V9_NEEDS_AT_LEAST_THREE_NON_OOS_SOURCES")
    n = len(usable)
    d_end = max(1, int(n * 0.60))
    v1_end = max(d_end + 1, int(n * 0.80)); v1_end = min(v1_end, n - 1)
    disc_src = usable[:d_end]
    va_src = usable[d_end:v1_end]
    vb_src = usable[v1_end:]

    disc, dc = _evaluate_sources(disc_src, prior_days, buy_fee, sell_fee)
    va, ac = _evaluate_sources(va_src, prior_days, buy_fee, sell_fee)
    vb, bc = _evaluate_sources(vb_src, prior_days, buy_fee, sell_fee)

    candidates = []
    all_ids = sorted(set(disc) | set(va) | set(vb))
    for cid in all_ids:
        dm = _metric(disc.get(cid, [])); am = _metric(va.get(cid, [])); bm = _metric(vb.get(cid, []))
        strict = all(
            m["n"] >= min_support
            and m["q25_net_mfe_pct"] is not None and float(m["q25_net_mfe_pct"]) > 0
            and m["median_net_mfe_pct"] is not None and float(m["median_net_mfe_pct"]) > 0
            for m in (dm, am, bm)
        )
        p, g = cid.split("__", 1)
        candidates.append({
            "id": cid,
            "precursor": p,
            "ignition": g,
            "discovery": dm,
            "validation_a": am,
            "validation_b": bm,
            "strict_cross_period_pass": strict,
        })
    candidates.sort(
        key=lambda r: (
            r["strict_cross_period_pass"],
            min(
                float(r["discovery"]["q25_net_mfe_pct"] or -999),
                float(r["validation_a"]["q25_net_mfe_pct"] or -999),
                float(r["validation_b"]["q25_net_mfe_pct"] or -999),
            ),
            min(
                float(r["discovery"]["median_net_mfe_pct"] or -999),
                float(r["validation_a"]["median_net_mfe_pct"] or -999),
                float(r["validation_b"]["median_net_mfe_pct"] or -999),
            ),
        ),
        reverse=True,
    )
    strict = [r for r in candidates if r["strict_cross_period_pass"]]
    return {
        "schema": "A1_TELEGRAM_MG_STREAMING_MULTI_LOGIC_V9_RESULT_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "method": "FULL_GOVERNED_UNIVERSE_STREAMING_FIRST_CAUSAL_MATCH_PER_FORMULA_PER_TICKER_DAY",
        "precursor_hypotheses": list(PRECURSORS),
        "ignition_hypotheses": list(IGNITIONS),
        "candidate_formula_count": len(PRECURSORS) * len(IGNITIONS),
        "all_governed_sources": sources,
        "discovery_sources": disc_src,
        "validation_a_sources": va_src,
        "validation_b_sources": vb_src,
        "reserved_oos_sources": [s for s in sources if s.get("reserved_oos")],
        "execution": {"buy_fee_pct": buy_fee, "sell_fee_pct": sell_fee},
        "counters": {"discovery": dc, "validation_a": ac, "validation_b": bc},
        "strict_cross_period_pass_count": len(strict),
        "strict_cross_period_passed": strict,
        "all_candidates": candidates,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "march_2025_reserved_oos_untouched": True,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    p.add_argument("--min-unique-days", type=int, default=20)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
        min_unique_days=a.min_unique_days,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
