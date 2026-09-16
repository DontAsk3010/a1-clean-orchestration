from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from . import telegram_mg_question_driven_v10 as v10
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .dual_lane_behavior_v1_cached import _governed_sources_from_durable_cache
from .telegram_mg_replay import _is_publication_slot

SCHEMA = "A1_DUAL_LANE_MULTI_LAYER_BEHAVIOR_MINER_V2"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")
RESERVED_OOS = v11.RESERVED_OOS

PRICE_METRICS = (
    "path_pct",
    "range_pct",
    "close_location",
    "drawdown_from_running_high_pct",
    "recovery_from_running_low_pct",
    "delta_path_pct",
)
FORMATION_METRICS = (
    "window_trade_value",
    "window_volume",
    "window_abs_nbss",
    "window_flow_imbalance",
    "window_haka",
    "window_haki",
    "window_two_sided_balance",
    "flow_coverage_fraction",
)


@dataclass
class BaselinePoint:
    values: dict[str, float | None]


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return float(a) / float(b)


def _pct(a: float | None, b: float | None) -> float | None:
    ratio = _safe_div(a, b)
    return None if ratio is None else (ratio - 1.0) * 100.0


def _sign(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "FLAT"


def _median(values: Iterable[float | None]) -> float | None:
    xs = [float(x) for x in values if x is not None and math.isfinite(float(x))]
    return float(median(xs)) if xs else None


def _rank(value: float | None, history: Sequence[float | None]) -> float | None:
    if value is None:
        return None
    xs = [float(x) for x in history if x is not None and math.isfinite(float(x))]
    if len(xs) < 3:
        return None
    less = sum(1 for x in xs if x < value)
    equal = sum(1 for x in xs if x == value)
    return (less + 0.5 * equal) / len(xs)


def _rank_bucket(rank: float | None) -> str:
    if rank is None:
        return "UNAVAILABLE"
    if rank < 0.25:
        return "Q1"
    if rank < 0.50:
        return "Q2"
    if rank < 0.75:
        return "Q3"
    return "Q4"


def _slot(timestamp: Any) -> str:
    text = str(timestamp or "")
    if " " in text:
        text = text.rsplit(" ", 1)[-1]
    return text[:5]


def _formation_window(
    *,
    value: float,
    volume: float,
    nbss: float,
    haka: float,
    haki: float,
    flow_rows: int,
    rows: int,
    prev_value: float,
    prev_volume: float,
    prev_nbss: float,
    prev_haka: float,
    prev_haki: float,
    prev_flow_rows: int,
    prev_rows: int,
) -> dict[str, float | None]:
    dv = value - prev_value
    dvol = volume - prev_volume
    dnbss = nbss - prev_nbss
    dhaka = haka - prev_haka
    dhaki = haki - prev_haki
    dflow_rows = flow_rows - prev_flow_rows
    drows = rows - prev_rows
    flow_value = dhaka + dhaki
    two_sided = None
    if flow_value > 0:
        two_sided = 2.0 * min(max(dhaka, 0.0), max(dhaki, 0.0)) / flow_value
    return {
        "window_trade_value": dv,
        "window_volume": dvol,
        "window_nbss": dnbss if dflow_rows > 0 else None,
        "window_abs_nbss": abs(dnbss) if dflow_rows > 0 else None,
        "window_haka": dhaka if dflow_rows > 0 else None,
        "window_haki": dhaki if dflow_rows > 0 else None,
        "window_flow_imbalance": _safe_div(dnbss, flow_value) if dflow_rows > 0 else None,
        "window_two_sided_balance": two_sided,
        "flow_coverage_fraction": _safe_div(float(dflow_rows), float(drows)) if drows > 0 else None,
    }


def derive_publication_snapshots(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not bars:
        return []
    first_open = _f(bars[0].get("open"))
    if first_open is None or first_open <= 0:
        return []

    run_hi: float | None = None
    run_lo: float | None = None
    cum_value = 0.0
    cum_volume = 0.0
    cum_nbss = 0.0
    cum_haka = 0.0
    cum_haki = 0.0
    flow_rows = 0
    rows = 0
    last_flow_sign: int | None = None
    flow_sign_changes = 0

    prev_pub_close: float | None = None
    prev_pub_path: float | None = None
    prev_pub_value = 0.0
    prev_pub_volume = 0.0
    prev_pub_nbss = 0.0
    prev_pub_haka = 0.0
    prev_pub_haki = 0.0
    prev_pub_flow_rows = 0
    prev_pub_rows = 0
    prev_window: dict[str, float | None] | None = None

    out: list[dict[str, Any]] = []
    for i, row in enumerate(bars):
        hi = _f(row.get("high")); lo = _f(row.get("low")); close = _f(row.get("close"))
        if hi is None or lo is None or close is None:
            continue
        run_hi = hi if run_hi is None else max(run_hi, hi)
        run_lo = lo if run_lo is None else min(run_lo, lo)
        rows += 1

        value = _f(row.get("trade_value"))
        volume = _f(row.get("volume"))
        if value is not None:
            cum_value += value
        if volume is not None:
            cum_volume += volume

        flow_ok = bool(row.get("flow_available", False)) and bool(row.get("mechanism_eligible", False))
        nbss = _f(row.get("nbss")) if flow_ok else None
        if value is not None and nbss is not None:
            haka = (value + nbss) / 2.0
            haki = (value - nbss) / 2.0
            if haka >= 0 and haki >= 0:
                cum_nbss += nbss
                cum_haka += haka
                cum_haki += haki
                flow_rows += 1
                sgn = 1 if nbss > 0 else -1 if nbss < 0 else 0
                if sgn and last_flow_sign and sgn != last_flow_sign:
                    flow_sign_changes += 1
                if sgn:
                    last_flow_sign = sgn

        if not _is_publication_slot(row.get("timestamp")):
            continue
        if run_hi is None or run_lo is None:
            continue

        path = _pct(close, first_open)
        rng = _pct(run_hi, run_lo) if run_lo > 0 else None
        loc = (close - run_lo) / (run_hi - run_lo) if run_hi > run_lo else 0.5
        drawdown = _pct(close, run_hi)
        recovery = _pct(close, run_lo)
        delta_path = None if path is None or prev_pub_path is None else path - prev_pub_path
        delta_close = _pct(close, prev_pub_close) if prev_pub_close not in (None, 0) else None

        window = _formation_window(
            value=cum_value,
            volume=cum_volume,
            nbss=cum_nbss,
            haka=cum_haka,
            haki=cum_haki,
            flow_rows=flow_rows,
            rows=rows,
            prev_value=prev_pub_value,
            prev_volume=prev_pub_volume,
            prev_nbss=prev_pub_nbss,
            prev_haka=prev_pub_haka,
            prev_haki=prev_pub_haki,
            prev_flow_rows=prev_pub_flow_rows,
            prev_rows=prev_pub_rows,
        )
        formation_rising = False
        formation_falling = False
        if prev_window is not None:
            comparisons = []
            for key in ("window_trade_value", "window_volume", "window_abs_nbss"):
                cur = _f(window.get(key)); prv = _f(prev_window.get(key))
                if cur is not None and prv is not None:
                    comparisons.append(cur - prv)
            formation_rising = any(x > 0 for x in comparisons)
            formation_falling = bool(comparisons) and all(x < 0 for x in comparisons)

        snapshot = {
            "index": i,
            "timestamp": str(row.get("timestamp") or ""),
            "slot": _slot(row.get("timestamp")),
            "price": {
                "open": first_open,
                "close": close,
                "path_pct": path,
                "range_pct": rng,
                "close_location": loc,
                "drawdown_from_running_high_pct": drawdown,
                "recovery_from_running_low_pct": recovery,
                "delta_path_pct": delta_path,
                "delta_close_pct": delta_close,
                "direction": _sign(delta_path),
                "fresh_running_high": hi >= run_hi,
                "fresh_running_low": lo <= run_lo,
                "open_is_running_low": math.isclose(first_open, run_lo, rel_tol=0.0, abs_tol=1e-12),
            },
            "formation": {
                **window,
                "cum_trade_value": cum_value,
                "cum_volume": cum_volume,
                "cum_nbss": cum_nbss if flow_rows else None,
                "cum_haka": cum_haka if flow_rows else None,
                "cum_haki": cum_haki if flow_rows else None,
                "flow_rows": flow_rows,
                "observed_rows": rows,
                "flow_sign_changes": flow_sign_changes,
                "formation_rising_vs_prev_pub": formation_rising,
                "formation_falling_vs_prev_pub": formation_falling,
            },
        }
        out.append(snapshot)
        prev_pub_close = close
        prev_pub_path = path
        prev_pub_value = cum_value
        prev_pub_volume = cum_volume
        prev_pub_nbss = cum_nbss
        prev_pub_haka = cum_haka
        prev_pub_haki = cum_haki
        prev_pub_flow_rows = flow_rows
        prev_pub_rows = rows
        prev_window = window
    return out


def _calibrate_snapshot(s: dict[str, Any], history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, float | None] = {}
    merged.update({k: _f(s["price"].get(k)) for k in PRICE_METRICS})
    merged.update({k: _f(s["formation"].get(k)) for k in FORMATION_METRICS})
    ranks: dict[str, float | None] = {}
    buckets: dict[str, str] = {}
    for key, value in merged.items():
        hist = [_f(x.get(key)) for x in history]
        rank = _rank(value, hist)
        ranks[key] = rank
        buckets[key] = _rank_bucket(rank)
    s["ranks"] = ranks
    s["rank_buckets"] = buckets
    s["baseline_count"] = len(history)
    return s


def _relation_state(s: Mapping[str, Any], prev: Mapping[str, Any] | None) -> str:
    p = s["price"]; f = s["formation"]; b = s.get("rank_buckets", {})
    direction = str(p.get("direction") or "UNKNOWN")
    flow = _f(f.get("window_nbss"))
    flow_sign = _sign(flow)
    activity_q4 = b.get("window_trade_value") == "Q4" or b.get("window_volume") == "Q4"
    flow_q4 = b.get("window_abs_nbss") == "Q4"
    formation_rising = bool(f.get("formation_rising_vs_prev_pub"))
    formation_active = activity_q4 or flow_q4 or formation_rising

    if formation_active and direction == "UP":
        return "ALIGNED_FORMATION_AND_PRICE_ADVANCE"
    if formation_active and flow_sign == "UP" and direction in {"FLAT", "DOWN"}:
        return "BUY_EFFORT_WITHOUT_UP_RESPONSE"
    if formation_active and flow_sign == "DOWN" and direction in {"FLAT", "UP"}:
        return "SELL_EFFORT_WITH_PRICE_RESILIENCE"
    if direction == "UP" and not formation_active:
        return "PRICE_ADVANCE_LEADS_FORMATION"
    if direction == "DOWN" and formation_active and flow_sign == "DOWN":
        return "ALIGNED_SELL_PRESSURE_AND_PRICE_DECLINE"
    if direction == "DOWN" and flow_sign == "UP":
        return "BUY_FLOW_PRICE_DIVERGENCE"
    if direction == "UP" and flow_sign == "DOWN":
        return "SELL_FLOW_PRICE_DIVERGENCE"
    if prev is not None:
        prev_rel = str(prev.get("relation_state") or "")
        if prev_rel == "BUY_EFFORT_WITHOUT_UP_RESPONSE" and direction == "UP" and formation_active:
            return "DELAYED_UP_RESPONSE_AFTER_BUY_EFFORT"
        if prev_rel == "PRICE_ADVANCE_LEADS_FORMATION" and formation_active:
            return "FORMATION_CATCHES_UP_TO_PRICE"
    return "MIXED_QUIET_OR_UNCALIBRATED"


def _action_state(relation: str, prev_relation: str | None) -> str:
    if relation in {"BUY_EFFORT_WITHOUT_UP_RESPONSE", "PRICE_ADVANCE_LEADS_FORMATION"}:
        return "WATCH_DEVELOPING"
    if relation in {"DELAYED_UP_RESPONSE_AFTER_BUY_EFFORT", "FORMATION_CATCHES_UP_TO_PRICE"}:
        return "CONFIRMING_CAUSAL_TRANSITION"
    if relation == "ALIGNED_FORMATION_AND_PRICE_ADVANCE":
        return "CONFIRMED_BEHAVIOR_STATE" if prev_relation and prev_relation != relation else "DEVELOPING_ALIGNED"
    if "DIVERGENCE" in relation or relation == "SELL_EFFORT_WITH_PRICE_RESILIENCE":
        return "ABSTAIN_OR_WATCH_CONTRADICTION"
    if relation == "ALIGNED_SELL_PRESSURE_AND_PRICE_DECLINE":
        return "WEAKENING_OR_FAILURE_CONTROL"
    return "NO_ACTION_INSUFFICIENT_EVIDENCE"


def _compress_relation_sequence(snaps: Sequence[Mapping[str, Any]]) -> list[str]:
    out: list[str] = []
    for s in snaps:
        rel = str(s.get("relation_state") or "")
        if rel and (not out or out[-1] != rel):
            out.append(rel)
    return out


def _metric(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "median_net_mfe_pct": None, "median_mae_pct": None, "median_eod_net_pct": None}
    return {
        "n": len(rows),
        "median_net_mfe_pct": _median([x[0] for x in rows]),
        "median_mae_pct": _median([x[1] for x in rows]),
        "median_eod_net_pct": _median([x[2] for x in rows]),
    }


def _iter_ngrams(seq: Sequence[str], min_n: int = 2, max_n: int = 5) -> Iterable[tuple[str, ...]]:
    for n in range(min_n, max_n + 1):
        if len(seq) < n:
            continue
        for i in range(0, len(seq) - n + 1):
            yield tuple(seq[i : i + n])


def build_report(*, prior_days: int = 20, buy_fee: float = 0.15, sell_fee: float = 0.25) -> dict[str, Any]:
    if RESERVED_OOS in (v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B):
        raise AssertionError("RESERVED_OOS_MUST_REMAIN_OUTSIDE_DEVELOPMENT")
    sources = _governed_sources_from_durable_cache()

    # ticker -> slot -> prior snapshots; only completed earlier days enter baseline.
    baseline: dict[str, dict[str, deque[dict[str, float | None]]]] = defaultdict(lambda: defaultdict(lambda: deque(maxlen=prior_days)))
    motif_outcomes = {b: defaultdict(list) for b in BLOCKS}
    motif_examples = {b: defaultdict(list) for b in BLOCKS}
    relation_counts = {b: Counter() for b in BLOCKS}
    action_counts = {b: Counter() for b in BLOCKS}
    price_twins: dict[str, dict[str, list[tuple[float, float, float]]]] = defaultdict(lambda: defaultdict(list))
    price_twin_examples: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    first_date_examples: list[dict[str, Any]] = []
    counters = {b: {"ticker_days": 0, "publication_slots": 0, "evaluable_motifs": 0} for b in BLOCKS}

    for src in sources:
        source = str(src["source_name"])
        block = v11._block_for(source)
        for packet in v12r._iter_cached(source):
            bars = [dict(x) for x in packet.get("bars", [])]
            if not bars:
                continue
            ticker = str(packet["ticker"]); date = str(packet["date"])
            counters[block]["ticker_days"] += 1
            snaps = derive_publication_snapshots(bars)
            if not snaps:
                continue

            calibrated: list[dict[str, Any]] = []
            for s in snaps:
                hist = list(baseline[ticker][str(s["slot"])])
                _calibrate_snapshot(s, hist)
                prev = calibrated[-1] if calibrated else None
                s["relation_state"] = _relation_state(s, prev)
                s["action_state"] = _action_state(s["relation_state"], None if prev is None else str(prev.get("relation_state")))
                relation_counts[block][s["relation_state"]] += 1
                action_counts[block][s["action_state"]] += 1
                counters[block]["publication_slots"] += 1
                calibrated.append(s)

            # Mine compressed relation sequences. Outcomes are attached only after the causal sequence exists.
            rel_seq = _compress_relation_sequence(calibrated)
            if rel_seq:
                relation_to_last_index: dict[str, int] = {}
                for i, s in enumerate(calibrated):
                    relation_to_last_index[str(s["relation_state"])] = i
                for motif in _iter_ngrams(rel_seq):
                    end_rel = motif[-1]
                    end_i = relation_to_last_index.get(end_rel)
                    if end_i is None:
                        continue
                    bar_i = int(calibrated[end_i]["index"])
                    hi, lo, final_close = v10._suffix(bars)
                    oc = v10._outcome(bars, bar_i, hi, lo, final_close, buy_fee, sell_fee)
                    if oc is None:
                        continue
                    key = " > ".join(motif)
                    motif_outcomes[block][key].append(oc)
                    counters[block]["evaluable_motifs"] += 1
                    if len(motif_examples[block][key]) < 3:
                        motif_examples[block][key].append({"source": source, "ticker": ticker, "date": date, "end_timestamp": calibrated[end_i]["timestamp"]})

            # Near-twin index: same three-step PRICE direction path, different formation signature.
            for j in range(2, len(calibrated)):
                win = calibrated[j - 2 : j + 1]
                price_sig = ">".join(str(x["price"]["direction"]) for x in win)
                formation_sig = ">".join(
                    f"{_sign(_f(x['formation'].get('window_nbss')))}:"
                    f"{x['rank_buckets'].get('window_trade_value','U')}:"
                    f"{x['rank_buckets'].get('window_two_sided_balance','U')}"
                    for x in win
                )
                bar_i = int(win[-1]["index"])
                hi, lo, final_close = v10._suffix(bars)
                oc = v10._outcome(bars, bar_i, hi, lo, final_close, buy_fee, sell_fee)
                if oc is not None:
                    price_twins[price_sig][formation_sig].append(oc)
                    ex_key = (price_sig, formation_sig)
                    if len(price_twin_examples[ex_key]) < 2:
                        price_twin_examples[ex_key].append({"source": source, "ticker": ticker, "date": date, "timestamp": win[-1]["timestamp"]})

            if source == v11.DISCOVERY[0] and date == "2024-12-02" and len(first_date_examples) < 20:
                first_date_examples.append({
                    "ticker": ticker,
                    "date": date,
                    "snapshots": [
                        {
                            "timestamp": x["timestamp"],
                            "price": x["price"],
                            "formation": x["formation"],
                            "rank_buckets": x["rank_buckets"],
                            "baseline_count": x["baseline_count"],
                            "relation_state": x["relation_state"],
                            "action_state": x["action_state"],
                        }
                        for x in calibrated[:20]
                    ],
                })

            # Baseline update happens only after this ticker-day is fully processed: no same-day future leakage.
            for s in calibrated:
                point: dict[str, float | None] = {}
                point.update({k: _f(s["price"].get(k)) for k in PRICE_METRICS})
                point.update({k: _f(s["formation"].get(k)) for k in FORMATION_METRICS})
                baseline[ticker][str(s["slot"])].append(point)

    motif_rows: list[dict[str, Any]] = []
    keys = {k for b in BLOCKS for k in motif_outcomes[b]}
    for key in keys:
        metrics = {b: _metric(motif_outcomes[b].get(key, [])) for b in BLOCKS}
        total_n = sum(int(metrics[b]["n"]) for b in BLOCKS)
        observed_blocks = sum(1 for b in BLOCKS if int(metrics[b]["n"]) > 0)
        motif_rows.append({
            "motif": key,
            "total_n": total_n,
            "observed_blocks": observed_blocks,
            "metrics": metrics,
            "examples": {b: motif_examples[b].get(key, []) for b in BLOCKS},
        })
    motif_rows.sort(key=lambda x: (x["observed_blocks"], x["total_n"]), reverse=True)

    twin_rows: list[dict[str, Any]] = []
    for price_sig, variants in price_twins.items():
        if len(variants) < 2:
            continue
        variant_rows = []
        medians = []
        for formation_sig, rows in variants.items():
            m = _metric(rows)
            med = m.get("median_net_mfe_pct")
            if med is not None:
                medians.append(float(med))
            variant_rows.append({
                "formation_signature": formation_sig,
                "metrics": m,
                "examples": price_twin_examples.get((price_sig, formation_sig), []),
            })
        spread = max(medians) - min(medians) if len(medians) >= 2 else None
        twin_rows.append({
            "same_price_signature": price_sig,
            "formation_variant_count": len(variant_rows),
            "median_net_mfe_spread_pct": spread,
            "formation_variants": sorted(variant_rows, key=lambda x: int(x["metrics"]["n"]), reverse=True)[:12],
        })
    twin_rows.sort(key=lambda x: (x["median_net_mfe_spread_pct"] is not None, x["median_net_mfe_spread_pct"] or -999.0), reverse=True)

    return {
        "schema": SCHEMA,
        "status": STATUS,
        "method": "CONTINUOUS_PRICE_BEHAVIOR_X_FORMATION_BEHAVIOR_WITH_EMPIRICAL_SAME_CLOCK_RANKS_AND_AUTOMATIC_SEQUENCE_MINING",
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "source_capability_boundary": {
            "used": ["OHLC", "volume", "validated_trade_value", "validated_NBSS_when_available", "derived_HAKA_HAKI_when_NBSS_eligible", "flow_coverage", "same_clock_prior_day_distributions"],
            "explicitly_not_invented": ["broker_participant_flow", "tick_time_and_trade", "L1_L2_orderbook", "queue_time_and_order", "financial_issuer_context"],
        },
        "important_semantics": {
            "price_behavior_and_formation_behavior_both_required": True,
            "raw_continuous_values_preserved_before_state_labels": True,
            "thresholds_from_same_clock_prior_distribution_not_outcome_tuning": True,
            "missing_flow_not_zero": True,
            "future_data_used_for_state": False,
            "future_data_used_only_for_outcome_evaluation": True,
            "first_available_day_may_be_uncalibrated_but_is_not_discarded": True,
        },
        "governed_blocks": {"DISCOVERY": list(v11.DISCOVERY), "VALIDATION_A": list(v11.VALIDATION_A), "VALIDATION_B": list(v11.VALIDATION_B), "RESERVED_OOS_UNTOUCHED": RESERVED_OOS},
        "execution": {"prior_days_same_clock_baseline": prior_days, "buy_fee_pct": buy_fee, "sell_fee_pct": sell_fee},
        "counters": counters,
        "relation_state_counts": {b: dict(relation_counts[b]) for b in BLOCKS},
        "research_action_state_counts": {b: dict(action_counts[b]) for b in BLOCKS},
        "automatically_mined_relation_motifs": motif_rows[:300],
        "same_price_near_twins_different_formation": twin_rows[:120],
        "earliest_december_2024_examples": first_date_examples,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=20)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    a = p.parse_args()
    report = build_report(prior_days=a.prior_days, buy_fee=a.buy_fee_pct, sell_fee=a.sell_fee_pct)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "counters": report["counters"],
        "relation_state_counts": report["relation_state_counts"],
        "top_motifs": report["automatically_mined_relation_motifs"][:10],
        "top_near_twins": report["same_price_near_twins_different_formation"][:10],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
