from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import telegram_mg_question_driven_v10 as v10
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_open_ladder_v13 import _eq
from .telegram_mg_replay import _is_publication_slot

SCHEMA = "A1_DUAL_LANE_PRICE_FORMATION_BEHAVIOR_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")

FORMULAS = (
    "DL01_FLOW_LEADS_PRICE_RELEASE_HOLD",
    "DL02_PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL",
    "DL03_EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP",
    "DL04_SELL_PRESSURE_RESILIENCE_CONTROL_TRANSFER",
    "DL05_TWO_WAVE_PRICE_FORMATION_RELOAD",
    "DL06_OPEN_LOW_DEFEND_RECLAIM_FORMATION",
    "DL07_FORMATION_PAUSE_PRICE_HOLD_REWAKE",
)

RELATIONSHIPS = (
    "ALIGNED_EXPANSION",
    "FORMATION_LEADS",
    "PRICE_LEADS",
    "BOTH_QUIET_OR_UNCONFIRMED",
)


@dataclass
class DualSequenceState:
    stage: int = 0
    max_stage: int = 0
    memory: dict[str, Any] = field(default_factory=dict)
    anchor_i: int | None = None
    last_i: int | None = None
    completed: bool = False
    invalidated: bool = False
    invalidation_reason: str | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _transition(st: DualSequenceState, stage: int, i: int, ts: str, label: str, **memory: Any) -> None:
    if st.anchor_i is None:
        st.anchor_i = i
    st.stage = stage
    st.max_stage = max(st.max_stage, stage)
    st.last_i = i
    st.memory.update(memory)
    st.transitions.append({"stage": stage, "index": i, "timestamp": ts, "label": label})


def _invalidate(st: DualSequenceState, i: int, ts: str, reason: str) -> None:
    st.invalidated = True
    st.invalidation_reason = reason
    st.last_i = i
    st.transitions.append({"stage": st.stage, "index": i, "timestamp": ts, "label": f"INVALIDATED:{reason}"})


def _complete(st: DualSequenceState, i: int, ts: str, label: str) -> bool:
    st.completed = True
    st.last_i = i
    st.transitions.append({"stage": st.stage, "index": i, "timestamp": ts, "label": label})
    return True


def _cache_ready(sources: Sequence[Mapping[str, Any]]) -> None:
    missing = [str(s["source_name"]) for s in sources if not v12r._meta_ok(str(s["source_name"]), s)]
    if missing:
        raise RuntimeError(f"DUAL_LANE_DURABLE_CACHE_REQUIRED_NO_RAW_REREAD:{missing}")


def _price_lane(
    base: Mapping[str, Any],
    row: Mapping[str, Any],
    prev: Mapping[str, Any] | None,
    prev_row: Mapping[str, Any] | None,
    op: float,
    run_low: float,
    run_high: float,
    prev_run_high: float | None,
) -> dict[str, Any]:
    path = _f(base.get("path"))
    prev_path = _f(prev.get("price", {}).get("path")) if prev else None
    cur_low = _f(row.get("low"))
    prev_low = _f(prev_row.get("low")) if prev_row else None
    cur_close = _f(row.get("close"))

    path_up = bool(base.get("path_up", False))
    accept = bool(base.get("accept", False))
    constructive = path_up and accept

    return {
        "path": path,
        "close": cur_close,
        "path_up_same_clock": path_up,
        "accept_same_clock": accept,
        "range_expand_same_clock": bool(base.get("range_expand", False)),
        "constructive": constructive,
        "progress_vs_prev_pub": path is not None and prev_path is not None and path > prev_path,
        "hold_vs_prev_pub": path is not None and prev_path is not None and path >= prev_path,
        "giveback_vs_prev_pub": path is not None and prev_path is not None and path < prev_path,
        "fresh_running_high": prev_run_high is not None and run_high > prev_run_high,
        "open_is_running_low": _eq(op, run_low),
        "low_stabilized_vs_prev_pub": cur_low is not None and prev_low is not None and cur_low >= prev_low,
    }


def _formation_lane(base: Mapping[str, Any], row: Mapping[str, Any], prev: Mapping[str, Any] | None) -> dict[str, Any]:
    value_wake = bool(base.get("value_wake", False))
    volume_wake = bool(base.get("volume_wake", False))
    flow_wake = bool(base.get("flow_wake", False))
    accel = bool(base.get("accel", False))
    flow_ratio = _f(base.get("nbss_to_value"))
    flow_available = bool(row.get("flow_available", False)) and bool(row.get("mechanism_eligible", False)) and flow_ratio is not None
    activity_active = value_wake or volume_wake or accel
    active = activity_active or (flow_available and flow_wake)

    prev_form = prev.get("formation", {}) if prev else {}
    prev_active = bool(prev_form.get("active", False))
    prev_flow_wake = bool(prev_form.get("flow_wake", False))

    return {
        "value_wake": value_wake,
        "volume_wake": volume_wake,
        "flow_wake": flow_wake if flow_available else False,
        "accel": accel,
        "activity_active": activity_active,
        "active": active,
        "persists": active and prev_active,
        "collapses": prev_active and not active,
        "flow_available": flow_available,
        "flow_ratio": flow_ratio if flow_available else None,
        "buy_flow": flow_available and flow_ratio is not None and flow_ratio > 0.0,
        "sell_flow": flow_available and flow_ratio is not None and flow_ratio < 0.0,
        "flow_persists": flow_available and flow_wake and prev_flow_wake,
        "value_ratio": _f(base.get("value_ratio")),
        "volume_ratio": _f(base.get("volume_ratio")),
    }


def _dual_snapshot(
    base: Mapping[str, Any],
    row: Mapping[str, Any],
    prev: Mapping[str, Any] | None,
    prev_row: Mapping[str, Any] | None,
    op: float,
    run_low: float,
    run_high: float,
    prev_run_high: float | None,
) -> dict[str, Any]:
    price = _price_lane(base, row, prev, prev_row, op, run_low, run_high, prev_run_high)
    formation = _formation_lane(base, row, prev)

    if price["constructive"] and formation["active"]:
        relationship = "ALIGNED_EXPANSION"
    elif formation["active"] and not price["constructive"]:
        relationship = "FORMATION_LEADS"
    elif price["constructive"] and not formation["active"]:
        relationship = "PRICE_LEADS"
    else:
        relationship = "BOTH_QUIET_OR_UNCONFIRMED"

    prev_path = _f(prev.get("price", {}).get("path")) if prev else None
    sell_pressure_resilience = (
        formation["sell_flow"]
        and price["path"] is not None
        and prev_path is not None
        and float(price["path"]) >= float(prev_path)
    )

    return {
        "timestamp": str(row.get("timestamp") or ""),
        "price": price,
        "formation": formation,
        "relationship": relationship,
        "sell_pressure_resilience": bool(sell_pressure_resilience),
    }


def _advance(fid: str, st: DualSequenceState, s: Mapping[str, Any], i: int) -> bool:
    if st.completed or st.invalidated:
        return False

    ts = str(s.get("timestamp") or "")
    p = s["price"]
    f = s["formation"]
    rel = str(s["relationship"])
    path = _f(p.get("path"))

    if fid == "DL01_FLOW_LEADS_PRICE_RELEASE_HOLD":
        if st.stage == 0 and rel == "FORMATION_LEADS" and f["flow_wake"]:
            _transition(st, 1, i, ts, "FLOW_LEADS", lead_path=path)
            return False
        if st.stage == 1:
            if f["collapses"]:
                _invalidate(st, i, ts, "FORMATION_COLLAPSE_BEFORE_PRICE_RESPONSE")
                return False
            if rel == "FORMATION_LEADS" and f["flow_wake"]:
                _transition(st, 2, i, ts, "FLOW_LEAD_PERSISTS")
                return False
        if st.stage == 2:
            if f["collapses"]:
                _invalidate(st, i, ts, "FORMATION_COLLAPSE_BEFORE_RELEASE")
                return False
            if rel == "ALIGNED_EXPANSION":
                _transition(st, 3, i, ts, "PRICE_RELEASE_ALIGNS", release_path=path)
                return False
        if st.stage == 3:
            release = _f(st.memory.get("release_path"))
            if f["collapses"] and p["giveback_vs_prev_pub"]:
                _invalidate(st, i, ts, "ALIGNED_RELEASE_NOT_RETAINED")
                return False
            if rel == "ALIGNED_EXPANSION" and path is not None and release is not None and path >= release:
                return _complete(st, i, ts, "ALIGNED_RELEASE_HOLDS")
        return False

    if fid == "DL02_PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL":
        if st.stage == 0 and rel == "PRICE_LEADS":
            _transition(st, 1, i, ts, "PRICE_LEADS", lead_path=path)
            return False
        if st.stage == 1:
            lead = _f(st.memory.get("lead_path"))
            if p["giveback_vs_prev_pub"] and not f["active"] and path is not None and lead is not None and path < lead:
                _invalidate(st, i, ts, "PRICE_LEAD_FAILED_BEFORE_FORMATION_CONFIRM")
                return False
            if rel == "ALIGNED_EXPANSION":
                _transition(st, 2, i, ts, "FORMATION_CONFIRMS_PRICE", confirm_path=path)
                return False
        if st.stage == 2:
            lead = _f(st.memory.get("lead_path"))
            confirm = _f(st.memory.get("confirm_path"))
            if f["collapses"] and p["giveback_vs_prev_pub"]:
                _invalidate(st, i, ts, "FORMATION_CONFIRM_COLLAPSES_ON_RETEST")
                return False
            if path is not None and confirm is not None and path < confirm and (lead is None or path >= lead) and f["active"]:
                _transition(st, 3, i, ts, "CONTROLLED_RETEST_WITH_FORMATION")
                return False
        if st.stage == 3:
            confirm = _f(st.memory.get("confirm_path"))
            if rel == "ALIGNED_EXPANSION" and path is not None and confirm is not None and path > confirm:
                return _complete(st, i, ts, "REACCELERATION_AFTER_CONFIRMED_RETEST")
        return False

    if fid == "DL03_EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP":
        effort = bool(f["activity_active"])
        if st.stage == 0 and effort and rel == "FORMATION_LEADS":
            _transition(st, 1, i, ts, "EFFORT_WITHOUT_PRICE_RESPONSE")
            return False
        if st.stage == 1:
            if f["collapses"]:
                _invalidate(st, i, ts, "EFFORT_DISAPPEARS_WITHOUT_RESPONSE")
                return False
            if effort and rel == "FORMATION_LEADS":
                _transition(st, 2, i, ts, "EFFORT_PERSISTS_WITHOUT_RESPONSE")
                return False
        if st.stage == 2 and rel == "ALIGNED_EXPANSION":
            _transition(st, 3, i, ts, "EFFICIENCY_FLIPS_POSITIVE", flip_path=path)
            return False
        if st.stage == 3:
            flip = _f(st.memory.get("flip_path"))
            if f["collapses"] and p["giveback_vs_prev_pub"]:
                _invalidate(st, i, ts, "EFFICIENCY_FLIP_NOT_RETAINED")
                return False
            if rel == "ALIGNED_EXPANSION" and path is not None and flip is not None and path >= flip:
                return _complete(st, i, ts, "EFFICIENCY_FLIP_HOLDS")
        return False

    if fid == "DL04_SELL_PRESSURE_RESILIENCE_CONTROL_TRANSFER":
        if st.stage == 0 and s["sell_pressure_resilience"]:
            _transition(st, 1, i, ts, "SELL_PRESSURE_WITH_LIMITED_DOWNSIDE")
            return False
        if st.stage == 1:
            if f["sell_flow"] and p["giveback_vs_prev_pub"] and not p["low_stabilized_vs_prev_pub"]:
                _invalidate(st, i, ts, "DOWNSIDE_RESUMES_UNDER_SELL_PRESSURE")
                return False
            if s["sell_pressure_resilience"] or (f["flow_available"] and p["low_stabilized_vs_prev_pub"]):
                _transition(st, 2, i, ts, "LOW_STABILIZES_WHILE_SELL_PRESSURE_LOSES_EFFECT")
                return False
        if st.stage == 2 and (f["buy_flow"] or f["flow_wake"]) and p["constructive"]:
            _transition(st, 3, i, ts, "CONTROL_TRANSFERS_WITH_PRICE_RESPONSE", transfer_path=path)
            return False
        if st.stage == 3:
            transfer = _f(st.memory.get("transfer_path"))
            if p["constructive"] and f["active"] and path is not None and transfer is not None and path >= transfer:
                return _complete(st, i, ts, "CONTROL_TRANSFER_HOLDS")
        return False

    if fid == "DL05_TWO_WAVE_PRICE_FORMATION_RELOAD":
        if st.stage == 0 and rel == "ALIGNED_EXPANSION":
            _transition(st, 1, i, ts, "FIRST_ALIGNED_IMPULSE", first_path=path)
            return False
        if st.stage == 1:
            first = _f(st.memory.get("first_path"))
            if f["collapses"] and p["giveback_vs_prev_pub"]:
                _invalidate(st, i, ts, "FORMATION_COLLAPSES_ON_FIRST_PULLBACK")
                return False
            if path is not None and first is not None and path < first and f["active"]:
                _transition(st, 2, i, ts, "PULLBACK_WITH_FORMATION_RETAINED")
                return False
        if st.stage == 2:
            first = _f(st.memory.get("first_path"))
            if rel == "ALIGNED_EXPANSION" and path is not None and first is not None and path > first:
                _transition(st, 3, i, ts, "SECOND_ALIGNED_IMPULSE", second_path=path)
                return False
        if st.stage == 3:
            second = _f(st.memory.get("second_path"))
            if p["constructive"] and f["active"] and path is not None and second is not None and path >= second:
                return _complete(st, i, ts, "SECOND_WAVE_HOLDS")
        return False

    if fid == "DL06_OPEN_LOW_DEFEND_RECLAIM_FORMATION":
        if st.stage == 0 and p["open_is_running_low"] and rel == "ALIGNED_EXPANSION":
            _transition(st, 1, i, ts, "OPEN_LOW_INITIAL_ALIGNED_PUSH", first_path=path)
            return False
        if st.stage == 1:
            if not p["open_is_running_low"]:
                _invalidate(st, i, ts, "OPEN_BROKEN_AFTER_INITIAL_PUSH")
                return False
            first = _f(st.memory.get("first_path"))
            if path is not None and first is not None and path < first and f["active"]:
                _transition(st, 2, i, ts, "OPEN_DEFENDED_PULLBACK_WITH_FORMATION")
                return False
        if st.stage == 2:
            if not p["open_is_running_low"]:
                _invalidate(st, i, ts, "OPEN_BROKEN_BEFORE_RECLAIM")
                return False
            if f["collapses"]:
                _invalidate(st, i, ts, "FORMATION_COLLAPSES_BEFORE_RECLAIM")
                return False
            first = _f(st.memory.get("first_path"))
            if rel == "ALIGNED_EXPANSION" and path is not None and first is not None and path > first:
                _transition(st, 3, i, ts, "RECLAIM_AND_REACCEL_WITH_FORMATION", reclaim_path=path)
                return False
        if st.stage == 3:
            reclaim = _f(st.memory.get("reclaim_path"))
            if not p["open_is_running_low"]:
                _invalidate(st, i, ts, "OPEN_BROKEN_AFTER_RECLAIM")
                return False
            if p["fresh_running_high"] and p["constructive"] and f["active"] and path is not None and reclaim is not None and path >= reclaim:
                return _complete(st, i, ts, "OPEN_DEFENDED_FRESH_HIGH_HOLDS")
        return False

    if fid == "DL07_FORMATION_PAUSE_PRICE_HOLD_REWAKE":
        if st.stage == 0 and rel == "ALIGNED_EXPANSION":
            _transition(st, 1, i, ts, "INITIAL_ALIGNED_EXPANSION", first_path=path)
            return False
        if st.stage == 1:
            first = _f(st.memory.get("first_path"))
            if f["collapses"] and path is not None and first is not None and path >= first:
                _transition(st, 2, i, ts, "FORMATION_PAUSES_PRICE_HOLDS")
                return False
            if f["collapses"] and path is not None and first is not None and path < first:
                _invalidate(st, i, ts, "FORMATION_AND_PRICE_BOTH_FAIL")
                return False
        if st.stage == 2 and rel == "ALIGNED_EXPANSION":
            first = _f(st.memory.get("first_path"))
            if path is not None and first is not None and path > first:
                _transition(st, 3, i, ts, "FORMATION_REWAKES_WITH_RENEWED_PRICE_PROGRESS", rewake_path=path)
                return False
        if st.stage == 3:
            rewake = _f(st.memory.get("rewake_path"))
            if p["constructive"] and f["active"] and path is not None and rewake is not None and path >= rewake:
                return _complete(st, i, ts, "REWAKE_PROGRESS_HOLDS")
        return False

    raise ValueError(f"UNKNOWN_DUAL_LANE_FORMULA:{fid}")


def _compact_snapshot(s: Mapping[str, Any]) -> dict[str, Any]:
    p = s["price"]
    f = s["formation"]
    return {
        "relationship": s["relationship"],
        "price": {
            "path": p.get("path"),
            "constructive": p.get("constructive"),
            "progress_vs_prev_pub": p.get("progress_vs_prev_pub"),
            "giveback_vs_prev_pub": p.get("giveback_vs_prev_pub"),
            "fresh_running_high": p.get("fresh_running_high"),
            "open_is_running_low": p.get("open_is_running_low"),
        },
        "formation": {
            "active": f.get("active"),
            "value_wake": f.get("value_wake"),
            "volume_wake": f.get("volume_wake"),
            "flow_available": f.get("flow_available"),
            "flow_wake": f.get("flow_wake"),
            "buy_flow": f.get("buy_flow"),
            "sell_flow": f.get("sell_flow"),
            "persists": f.get("persists"),
            "collapses": f.get("collapses"),
        },
    }


def _metric(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    return v12r._metric(rows)


def _strict(metrics: Mapping[str, Mapping[str, Any]], min_support: int) -> bool:
    return v12r._strict(metrics, min_support)


def build_report(*, prior_days: int = 10, buy_fee: float = 0.15, sell_fee: float = 0.25, min_support: int = 40) -> dict[str, Any]:
    sources = v11._ordered_governed_sources()
    _cache_ready(sources)

    results = {b: defaultdict(list) for b in BLOCKS}
    examples = {b: defaultdict(list) for b in BLOCKS}
    near_twins = {b: defaultdict(list) for b in BLOCKS}
    near_twin_reasons = {b: defaultdict(Counter) for b in BLOCKS}
    diagnostics = {b: defaultdict(list) for b in BLOCKS}
    counters = {b: {"ticker_days": 0, "publication_slots": 0, "signals": 0, "near_twins": 0} for b in BLOCKS}

    hist_day: dict[str, list[v10.DayBehavior]] = defaultdict(list)
    hist_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)

    for src in sources:
        source = str(src["source_name"])
        block = v11._block_for(source)
        for packet in v12r._iter_cached(source):
            bars = [dict(x) for x in packet.get("bars", [])]
            if not bars:
                continue
            ticker = str(packet["ticker"])
            date = str(packet["date"])
            counters[block]["ticker_days"] += 1

            hd = hist_day[ticker][-prior_days:]
            hp = hist_prefix[ticker][-prior_days:]
            cur = v11._prefix_series(bars)
            hi, lo, final_close = v10._suffix(bars)

            states = {fid: DualSequenceState() for fid in FORMULAS}
            signaled: set[str] = set()
            seen_diag: set[str] = set()
            prev_snap: dict[str, Any] | None = None
            prev_row: dict[str, Any] | None = None
            run_low: float | None = None
            run_high: float | None = None
            prev_run_high: float | None = None

            opens = [_f(x.get("open")) for x in bars if _f(x.get("open")) is not None]
            op = opens[0] if opens else None

            if len(hp) >= 3 and op is not None and op > 0:
                for i, row in enumerate(bars):
                    low_i = _f(row.get("low"))
                    high_i = _f(row.get("high"))
                    if low_i is not None:
                        run_low = low_i if run_low is None else min(run_low, low_i)
                    if high_i is not None:
                        run_high = high_i if run_high is None else max(run_high, high_i)

                    if not _is_publication_slot(row.get("timestamp")):
                        continue
                    if run_low is None or run_high is None:
                        continue
                    counters[block]["publication_slots"] += 1

                    base = v11._snapshot(cur, hp, i)
                    if not base:
                        continue
                    snap = _dual_snapshot(base, row, prev_snap, prev_row, float(op), run_low, run_high, prev_run_high)

                    diag_keys = {
                        "PRICE_CONSTRUCTIVE": bool(snap["price"]["constructive"]),
                        "FORMATION_ACTIVE": bool(snap["formation"]["active"]),
                        f"REL_{snap['relationship']}": True,
                        "SELL_PRESSURE_RESILIENCE": bool(snap["sell_pressure_resilience"]),
                    }
                    for key, active in diag_keys.items():
                        if not active or key in seen_diag:
                            continue
                        oc = v10._outcome(bars, i, hi, lo, final_close, buy_fee, sell_fee)
                        if oc is not None:
                            diagnostics[block][key].append(oc)
                            seen_diag.add(key)

                    for fid, st in states.items():
                        if fid in signaled or st.invalidated:
                            continue
                        if _advance(fid, st, snap, i):
                            oc = v10._outcome(bars, i, hi, lo, final_close, buy_fee, sell_fee)
                            if oc is None:
                                continue
                            results[block][fid].append(oc)
                            counters[block]["signals"] += 1
                            signaled.add(fid)
                            if len(examples[block][fid]) < 8:
                                examples[block][fid].append({
                                    "source": source,
                                    "ticker": ticker,
                                    "date": date,
                                    "timestamp": row.get("timestamp"),
                                    "signal_snapshot": _compact_snapshot(snap),
                                    "transitions": list(st.transitions),
                                    "net_mfe_pct": oc[0],
                                    "mae_pct": oc[1],
                                    "eod_net_pct": oc[2],
                                })

                    prev_snap = snap
                    prev_row = row
                    prev_run_high = run_high

                for fid, st in states.items():
                    if st.completed or st.max_stage < 2 or st.last_i is None:
                        continue
                    oc = v10._outcome(bars, st.last_i, hi, lo, final_close, buy_fee, sell_fee)
                    if oc is None:
                        continue
                    reason = st.invalidation_reason or "INCOMPLETE_BEFORE_CLOSE"
                    near_twins[block][fid].append(oc)
                    near_twin_reasons[block][fid][reason] += 1
                    counters[block]["near_twins"] += 1

            day_behavior = v10._day_behavior(bars, date)
            if day_behavior is not None:
                hist_day[ticker].append(day_behavior)
                hist_day[ticker] = hist_day[ticker][-prior_days:]
                hist_prefix[ticker].append(cur)
                hist_prefix[ticker] = hist_prefix[ticker][-prior_days:]

    formulas: list[dict[str, Any]] = []
    for fid in FORMULAS:
        metrics = {b: _metric(results[b].get(fid, [])) for b in BLOCKS}
        nt_metrics = {b: _metric(near_twins[b].get(fid, [])) for b in BLOCKS}
        strict = _strict(metrics, min_support)
        q25s = [metrics[b].get("q25_net_mfe_pct") for b in BLOCKS]
        meds = [metrics[b].get("median_net_mfe_pct") for b in BLOCKS]
        worst_q25 = min(float(x) if x is not None else -999.0 for x in q25s)
        worst_med = min(float(x) if x is not None else -999.0 for x in meds)
        formulas.append({
            "id": fid,
            "strict_cross_period_pass": strict,
            "worst_block_q25_net_mfe_pct": worst_q25,
            "worst_block_median_net_mfe_pct": worst_med,
            "signal_metrics": metrics,
            "near_twin_metrics": nt_metrics,
            "near_twin_divergence_reasons": {b: dict(near_twin_reasons[b].get(fid, {})) for b in BLOCKS},
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

    diagnostic_metrics: dict[str, Any] = {}
    all_diag_keys = sorted({k for b in BLOCKS for k in diagnostics[b]})
    for key in all_diag_keys:
        diagnostic_metrics[key] = {b: _metric(diagnostics[b].get(key, [])) for b in BLOCKS}

    survivors = [x for x in formulas if x["strict_cross_period_pass"]]
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "method": "SYNCHRONIZED_PRICE_LANE_X_FORMATION_LANE_WITH_RELATIONSHIP_STATE",
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "source_capability_boundary": {
            "used": ["OHLC", "volume", "validated_trade_value", "validated_flow_NBSS_when_available", "same_clock_prefix_features", "prior_day_behavior_context"],
            "not_assumed_without_source": ["broker_participant_flow", "tick_time_and_trade", "L1_L2_orderbook", "queue_time_and_order", "financial_issuer_context"],
        },
        "governed_blocks": {
            "DISCOVERY": list(v11.DISCOVERY),
            "VALIDATION_A": list(v11.VALIDATION_A),
            "VALIDATION_B": list(v11.VALIDATION_B),
            "RESERVED_OOS_UNTOUCHED": v11.RESERVED_OOS,
        },
        "formula_count": len(FORMULAS),
        "formulas_tested": list(FORMULAS),
        "relationship_states": list(RELATIONSHIPS),
        "execution": {"prior_days": prior_days, "buy_fee_pct": buy_fee, "sell_fee_pct": sell_fee, "min_support": min_support},
        "counters": counters,
        "diagnostic_first_occurrence_metrics": diagnostic_metrics,
        "strict_survivor_count": len(survivors),
        "strict_survivors": survivors,
        "ranked_formulas": formulas,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
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
    print(json.dumps({
        "strict_survivor_count": report["strict_survivor_count"],
        "counters": report["counters"],
        "top": report["ranked_formulas"][:3],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
