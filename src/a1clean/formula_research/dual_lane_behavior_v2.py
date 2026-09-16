from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from . import telegram_mg_question_driven_v10 as v10
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .durable_cache_catalog import governed_sources_from_durable_cache as _governed_sources_from_durable_cache
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
    "window_nbss_to_value",
    "flow_coverage_fraction",
    "window_flow_sign_changes",
)


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


def _window_formation(
    *,
    value: float,
    volume: float,
    nbss: float,
    flow_rows: int,
    rows: int,
    flow_sign_changes: int,
    prev_value: float,
    prev_volume: float,
    prev_nbss: float,
    prev_flow_rows: int,
    prev_rows: int,
    prev_flow_sign_changes: int,
) -> dict[str, float | None]:
    dv = value - prev_value
    dvol = volume - prev_volume
    dflow_rows = flow_rows - prev_flow_rows
    drows = rows - prev_rows
    dnbss = nbss - prev_nbss if dflow_rows > 0 else None
    return {
        "window_trade_value": dv,
        "window_volume": dvol,
        "window_nbss": dnbss,
        "window_abs_nbss": abs(dnbss) if dnbss is not None else None,
        "window_nbss_to_value": _safe_div(dnbss, dv) if dnbss is not None else None,
        "flow_coverage_fraction": _safe_div(float(dflow_rows), float(drows)) if drows > 0 else None,
        "window_flow_sign_changes": float(flow_sign_changes - prev_flow_sign_changes) if dflow_rows > 0 else None,
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
    flow_rows = 0
    rows = 0
    last_flow_sign: int | None = None
    flow_sign_changes = 0

    prev_pub_close: float | None = None
    prev_pub_path: float | None = None
    prev_pub_value = 0.0
    prev_pub_volume = 0.0
    prev_pub_nbss = 0.0
    prev_pub_flow_rows = 0
    prev_pub_rows = 0
    prev_pub_flow_sign_changes = 0
    prev_window: dict[str, float | None] | None = None

    out: list[dict[str, Any]] = []
    for i, row in enumerate(bars):
        hi = _f(row.get("high"))
        lo = _f(row.get("low"))
        close = _f(row.get("close"))
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
        if nbss is not None:
            cum_nbss += nbss
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

        window = _window_formation(
            value=cum_value,
            volume=cum_volume,
            nbss=cum_nbss,
            flow_rows=flow_rows,
            rows=rows,
            flow_sign_changes=flow_sign_changes,
            prev_value=prev_pub_value,
            prev_volume=prev_pub_volume,
            prev_nbss=prev_pub_nbss,
            prev_flow_rows=prev_pub_flow_rows,
            prev_rows=prev_pub_rows,
            prev_flow_sign_changes=prev_pub_flow_sign_changes,
        )

        formation_rising = False
        formation_falling = False
        if prev_window is not None:
            comparisons: list[float] = []
            for key in ("window_trade_value", "window_volume", "window_abs_nbss"):
                cur = _f(window.get(key))
                prv = _f(prev_window.get(key))
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
                "flow_rows": flow_rows,
                "observed_rows": rows,
                "cum_flow_sign_changes": flow_sign_changes,
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
        prev_pub_flow_rows = flow_rows
        prev_pub_rows = rows
        prev_pub_flow_sign_changes = flow_sign_changes
        prev_window = window

    return out


def _calibrate_snapshot(snapshot: dict[str, Any], history: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    merged: dict[str, float | None] = {}
    merged.update({k: _f(snapshot["price"].get(k)) for k in PRICE_METRICS})
    merged.update({k: _f(snapshot["formation"].get(k)) for k in FORMATION_METRICS})
    ranks: dict[str, float | None] = {}
    buckets: dict[str, str] = {}
    for key, value in merged.items():
        hist = [_f(x.get(key)) for x in history]
        rank = _rank(value, hist)
        ranks[key] = rank
        buckets[key] = _rank_bucket(rank)
    snapshot["ranks"] = ranks
    snapshot["rank_buckets"] = buckets
    snapshot["baseline_count"] = len(history)
    return snapshot


def _formation_is_active(snapshot: Mapping[str, Any]) -> bool:
    buckets = snapshot.get("rank_buckets", {})
    formation = snapshot["formation"]
    empirical_high = any(
        buckets.get(key) == "Q4"
        for key in ("window_trade_value", "window_volume", "window_abs_nbss")
    )
    return empirical_high or bool(formation.get("formation_rising_vs_prev_pub", False))


def _relation_state(snapshot: Mapping[str, Any], prev: Mapping[str, Any] | None) -> str:
    price = snapshot["price"]
    formation = snapshot["formation"]
    direction = str(price.get("direction") or "UNKNOWN")
    flow_sign = _sign(_f(formation.get("window_nbss")))
    active = _formation_is_active(snapshot)

    if prev is not None:
        prev_rel = str(prev.get("relation_state") or "")
        if prev_rel == "BUY_FLOW_WITHOUT_PRICE_PROGRESS" and direction == "UP" and active:
            return "DELAYED_UP_RESPONSE_AFTER_BUY_FLOW"
        if prev_rel == "PRICE_ADVANCE_LOW_FORMATION" and active:
            return "FORMATION_CATCHES_UP_TO_PRICE"

    if active and direction == "UP" and flow_sign in {"UP", "UNKNOWN", "FLAT"}:
        return "ALIGNED_FORMATION_AND_PRICE_ADVANCE"
    if active and flow_sign == "UP" and direction in {"FLAT", "DOWN"}:
        return "BUY_FLOW_WITHOUT_PRICE_PROGRESS"
    if active and flow_sign == "DOWN" and direction in {"FLAT", "UP"}:
        return "SELL_FLOW_WITH_PRICE_RESILIENCE"
    if direction == "UP" and not active:
        return "PRICE_ADVANCE_LOW_FORMATION"
    if direction == "DOWN" and active and flow_sign == "DOWN":
        return "ALIGNED_SELL_PRESSURE_AND_PRICE_DECLINE"
    if direction == "DOWN" and flow_sign == "UP":
        return "BUY_FLOW_PRICE_DIVERGENCE"
    if direction == "UP" and flow_sign == "DOWN":
        return "SELL_FLOW_PRICE_DIVERGENCE"
    return "MIXED_QUIET_OR_UNCALIBRATED"


def _action_state(relation: str, prev_relation: str | None) -> str:
    if relation in {"BUY_FLOW_WITHOUT_PRICE_PROGRESS", "PRICE_ADVANCE_LOW_FORMATION"}:
        return "WATCH_DEVELOPING"
    if relation in {"DELAYED_UP_RESPONSE_AFTER_BUY_FLOW", "FORMATION_CATCHES_UP_TO_PRICE"}:
        return "CONFIRMING_CAUSAL_TRANSITION"
    if relation == "ALIGNED_FORMATION_AND_PRICE_ADVANCE":
        return "CONFIRMED_BEHAVIOR_STATE" if prev_relation and prev_relation != relation else "DEVELOPING_ALIGNED"
    if "DIVERGENCE" in relation or relation == "SELL_FLOW_WITH_PRICE_RESILIENCE":
        return "ABSTAIN_OR_WATCH_CONTRADICTION"
    if relation == "ALIGNED_SELL_PRESSURE_AND_PRICE_DECLINE":
        return "WEAKENING_OR_FAILURE_CONTROL"
    return "NO_ACTION_INSUFFICIENT_EVIDENCE"


def _compressed_relation_occurrences(snaps: Sequence[Mapping[str, Any]]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for i, snapshot in enumerate(snaps):
        relation = str(snapshot.get("relation_state") or "")
        if not relation:
            continue
        if out and out[-1][0] == relation:
            out[-1] = (relation, i)
        else:
            out.append((relation, i))
    return out


def _metric(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "median_net_mfe_pct": None,
            "median_mae_pct": None,
            "median_eod_net_pct": None,
        }
    return {
        "n": len(rows),
        "median_net_mfe_pct": _median([x[0] for x in rows]),
        "median_mae_pct": _median([x[1] for x in rows]),
        "median_eod_net_pct": _median([x[2] for x in rows]),
    }


def _iter_relation_ngrams(
    seq: Sequence[tuple[str, int]],
    min_n: int = 2,
    max_n: int = 5,
) -> Iterable[tuple[tuple[str, ...], int]]:
    for n in range(min_n, max_n + 1):
        if len(seq) < n:
            continue
        for i in range(0, len(seq) - n + 1):
            window = seq[i : i + n]
            yield tuple(x[0] for x in window), int(window[-1][1])


def _formation_signature(snapshot: Mapping[str, Any]) -> str:
    formation = snapshot["formation"]
    buckets = snapshot.get("rank_buckets", {})
    return ":".join(
        [
            _sign(_f(formation.get("window_nbss"))),
            str(buckets.get("window_trade_value", "UNAVAILABLE")),
            str(buckets.get("window_volume", "UNAVAILABLE")),
            str(buckets.get("window_abs_nbss", "UNAVAILABLE")),
            str(buckets.get("window_nbss_to_value", "UNAVAILABLE")),
        ]
    )


def build_report(*, prior_days: int = 20, buy_fee: float = 0.15, sell_fee: float = 0.25) -> dict[str, Any]:
    if RESERVED_OOS in (v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B):
        raise AssertionError("RESERVED_OOS_MUST_REMAIN_OUTSIDE_DEVELOPMENT")
    sources = _governed_sources_from_durable_cache()

    baseline: dict[str, dict[str, deque[dict[str, float | None]]]] = defaultdict(
        lambda: defaultdict(lambda: deque(maxlen=prior_days))
    )
    motif_outcomes = {b: defaultdict(list) for b in BLOCKS}
    motif_examples = {b: defaultdict(list) for b in BLOCKS}
    relation_counts = {b: Counter() for b in BLOCKS}
    action_counts = {b: Counter() for b in BLOCKS}
    price_twins: dict[str, dict[str, list[tuple[float, float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    price_twin_examples: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    first_date_examples: list[dict[str, Any]] = []
    counters = {
        b: {"ticker_days": 0, "publication_slots": 0, "evaluable_motifs": 0}
        for b in BLOCKS
    }

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
            snaps = derive_publication_snapshots(bars)
            if not snaps:
                continue

            calibrated: list[dict[str, Any]] = []
            for snapshot in snaps:
                hist = list(baseline[ticker][str(snapshot["slot"])])
                _calibrate_snapshot(snapshot, hist)
                prev = calibrated[-1] if calibrated else None
                snapshot["relation_state"] = _relation_state(snapshot, prev)
                snapshot["action_state"] = _action_state(
                    snapshot["relation_state"],
                    None if prev is None else str(prev.get("relation_state")),
                )
                relation_counts[block][snapshot["relation_state"]] += 1
                action_counts[block][snapshot["action_state"]] += 1
                counters[block]["publication_slots"] += 1
                calibrated.append(snapshot)

            hi, lo, final_close = v10._suffix(bars)

            compressed = _compressed_relation_occurrences(calibrated)
            seen_motifs_this_day: set[str] = set()
            for motif, end_snapshot_i in _iter_relation_ngrams(compressed):
                key = " > ".join(motif)
                if key in seen_motifs_this_day:
                    continue
                bar_i = int(calibrated[end_snapshot_i]["index"])
                outcome = v10._outcome(bars, bar_i, hi, lo, final_close, buy_fee, sell_fee)
                if outcome is None:
                    continue
                seen_motifs_this_day.add(key)
                motif_outcomes[block][key].append(outcome)
                counters[block]["evaluable_motifs"] += 1
                if len(motif_examples[block][key]) < 3:
                    motif_examples[block][key].append(
                        {
                            "source": source,
                            "ticker": ticker,
                            "date": date,
                            "end_timestamp": calibrated[end_snapshot_i]["timestamp"],
                        }
                    )

            for j in range(2, len(calibrated)):
                win = calibrated[j - 2 : j + 1]
                price_sig = ">".join(str(x["price"]["direction"]) for x in win)
                formation_sig = ">".join(_formation_signature(x) for x in win)
                bar_i = int(win[-1]["index"])
                outcome = v10._outcome(bars, bar_i, hi, lo, final_close, buy_fee, sell_fee)
                if outcome is not None:
                    price_twins[price_sig][formation_sig].append(outcome)
                    ex_key = (price_sig, formation_sig)
                    if len(price_twin_examples[ex_key]) < 2:
                        price_twin_examples[ex_key].append(
                            {
                                "source": source,
                                "ticker": ticker,
                                "date": date,
                                "timestamp": win[-1]["timestamp"],
                            }
                        )

            if source == v11.DISCOVERY[0] and date == "2024-12-02" and len(first_date_examples) < 20:
                first_date_examples.append(
                    {
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
                    }
                )

            # Only completed earlier ticker-days enter later same-clock baselines.
            for snapshot in calibrated:
                point: dict[str, float | None] = {}
                point.update({k: _f(snapshot["price"].get(k)) for k in PRICE_METRICS})
                point.update({k: _f(snapshot["formation"].get(k)) for k in FORMATION_METRICS})
                baseline[ticker][str(snapshot["slot"])].append(point)

    motif_rows: list[dict[str, Any]] = []
    keys = {k for b in BLOCKS for k in motif_outcomes[b]}
    for key in keys:
        metrics = {b: _metric(motif_outcomes[b].get(key, [])) for b in BLOCKS}
        total_n = sum(int(metrics[b]["n"]) for b in BLOCKS)
        observed_blocks = sum(1 for b in BLOCKS if int(metrics[b]["n"]) > 0)
        motif_rows.append(
            {
                "motif": key,
                "total_n": total_n,
                "observed_blocks": observed_blocks,
                "metrics": metrics,
                "examples": {b: motif_examples[b].get(key, []) for b in BLOCKS},
            }
        )
    motif_rows.sort(key=lambda x: (x["observed_blocks"], x["total_n"]), reverse=True)

    twin_rows: list[dict[str, Any]] = []
    for price_sig, variants in price_twins.items():
        if len(variants) < 2:
            continue
        variant_rows = []
        medians = []
        for formation_sig, rows in variants.items():
            metrics = _metric(rows)
            med = metrics.get("median_net_mfe_pct")
            if med is not None:
                medians.append(float(med))
            variant_rows.append(
                {
                    "formation_signature": formation_sig,
                    "metrics": metrics,
                    "examples": price_twin_examples.get((price_sig, formation_sig), []),
                }
            )
        spread = max(medians) - min(medians) if len(medians) >= 2 else None
        twin_rows.append(
            {
                "same_price_signature": price_sig,
                "formation_variant_count": len(variant_rows),
                "median_net_mfe_spread_pct": spread,
                "formation_variants": sorted(
                    variant_rows,
                    key=lambda x: int(x["metrics"]["n"]),
                    reverse=True,
                )[:12],
            }
        )
    twin_rows.sort(
        key=lambda x: (
            x["median_net_mfe_spread_pct"] is not None,
            x["median_net_mfe_spread_pct"] or -999.0,
        ),
        reverse=True,
    )

    return {
        "schema": SCHEMA,
        "status": STATUS,
        "method": "CONTINUOUS_PRICE_BEHAVIOR_X_FORMATION_BEHAVIOR_WITH_EMPIRICAL_SAME_CLOCK_RANKS_AND_AUTOMATIC_SEQUENCE_MINING",
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "source_capability_boundary": {
            "used": [
                "OHLC",
                "volume",
                "validated_trade_value",
                "validated_NBSS_when_available",
                "flow_coverage",
                "same_clock_prior_day_distributions",
            ],
            "available_later_only_if_proven_not_derived_here": [
                "HAKA_HAKI",
                "broker_participant_flow",
                "tick_time_and_trade",
                "L1_L2_orderbook",
                "queue_time_and_order",
                "financial_issuer_context",
            ],
        },
        "important_semantics": {
            "price_behavior_and_formation_behavior_both_required": True,
            "raw_continuous_values_preserved_before_state_labels": True,
            "thresholds_from_same_clock_prior_distribution_not_outcome_tuning": True,
            "missing_flow_not_zero": True,
            "haka_haki_not_derived_from_trade_value_and_nbss_without_source_contract": True,
            "future_data_used_for_state": False,
            "future_data_used_only_for_outcome_evaluation": True,
            "first_available_day_may_be_uncalibrated_but_is_not_discarded": True,
        },
        "governed_blocks": {
            "DISCOVERY": list(v11.DISCOVERY),
            "VALIDATION_A": list(v11.VALIDATION_A),
            "VALIDATION_B": list(v11.VALIDATION_B),
            "RESERVED_OOS_UNTOUCHED": RESERVED_OOS,
        },
        "execution": {
            "prior_days_same_clock_baseline": prior_days,
            "buy_fee_pct": buy_fee,
            "sell_fee_pct": sell_fee,
        },
        "counters": counters,
        "relation_state_counts": {b: dict(relation_counts[b]) for b in BLOCKS},
        "research_action_state_counts": {b: dict(action_counts[b]) for b in BLOCKS},
        "automatically_mined_relation_motifs": motif_rows[:300],
        "same_price_near_twins_different_formation": twin_rows[:120],
        "earliest_december_2024_examples": first_date_examples,
        "march_2025_reserved_oos_touched": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--prior-days", type=int, default=20)
    parser.add_argument("--buy-fee-pct", type=float, default=0.15)
    parser.add_argument("--sell-fee-pct", type=float, default=0.25)
    args = parser.parse_args()
    report = build_report(
        prior_days=args.prior_days,
        buy_fee=args.buy_fee_pct,
        sell_fee=args.sell_fee_pct,
    )
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "counters": report["counters"],
                "relation_state_counts": report["relation_state_counts"],
                "top_motifs": report["automatically_mined_relation_motifs"][:10],
                "top_near_twins": report["same_price_near_twins_different_formation"][:10],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
