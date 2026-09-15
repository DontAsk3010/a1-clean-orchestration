from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from json import dumps
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE, FALSE, evaluate_intraday_candidates
from .telegram_mg_multiday_context_study import DayRecord, _history_context
from .telegram_mg_replay import evaluate_mg_packet

TOPOLOGIES = (
    "J01_WAKE_RESPONSE_RETENTION",
    "J02_RECOVERY_RECLAIM",
    "J03_COMPRESSION_EXPANSION",
    "J04_PULLBACK_REACCELERATION",
    "J05_FLOW_RESILIENT_CONTINUATION",
    "J06_EARLY_STRENGTH_RETAINED",
)


def _num(v: Any) -> float | None:
    if v is None:
        return None
    return float(v)


def _is_true(v: Any) -> bool:
    return v == TRUE or v is True


def _is_false(v: Any) -> bool:
    return v == FALSE or v is False


def _quantile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not clean:
        return None
    if q <= 0:
        return clean[0]
    if q >= 1:
        return clean[-1]
    pos = (len(clean) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return clean[lo]
    w = pos - lo
    return clean[lo] * (1 - w) + clean[hi] * w


def _observed_step(bars: Sequence[Mapping[str, Any]], index: int, lookback: int = 30) -> float | None:
    """Causal historical price-step proxy. Never uses bars after index."""
    start = max(0, index - lookback + 1)
    vals: list[float] = []
    for row in bars[start:index + 1]:
        for k in ("open", "high", "low", "close"):
            x = _num(row.get(k))
            if x is not None and x > 0:
                vals.append(x)
    uniq = sorted(set(vals))
    diffs = [b - a for a, b in zip(uniq, uniq[1:]) if b - a > 1e-9]
    return min(diffs) if diffs else None


def _net_return_pct(entry: float, exit_price: float, buy_fee_pct: float, sell_fee_pct: float) -> float:
    buy_cost = entry * (1 + buy_fee_pct / 100.0)
    sell_net = exit_price * (1 - sell_fee_pct / 100.0)
    return (sell_net / buy_cost - 1.0) * 100.0


def _execution_net(entry: float, exit_price: float, shares: int, buy_fee_pct: float, sell_fee_pct: float) -> float:
    return exit_price * shares * (1 - sell_fee_pct / 100.0) - entry * shares * (1 + buy_fee_pct / 100.0)


def _previous_regular_close(history: Mapping[str, DayRecord], prior_dates: Sequence[str]) -> float | None:
    for d in reversed(prior_dates):
        rec = history.get(d)
        if rec and rec.bars:
            for row in reversed(rec.bars):
                c = _num(row.get("close"))
                if c is not None and c > 0:
                    return c
    return None


def _pullback_reaccel_features(
    bars: Sequence[Mapping[str, Any]], index: int, params: CandidateParams
) -> dict[str, bool | None]:
    """Structural, causal pullback->reclaim features without future bars."""
    if index < max(params.high_lookback, 3) + 2:
        return {"had_pullback": None, "reclaim": None, "renewed_high": None}
    closes = [_num(r.get("close")) for r in bars[:index + 1]]
    highs = [_num(r.get("high")) for r in bars[:index + 1]]
    if any(v is None for v in closes[max(0, index - params.recovery_lookback):index + 1]):
        return {"had_pullback": None, "reclaim": None, "renewed_high": None}
    start = max(0, index - params.recovery_lookback)
    prior = [float(v) for v in closes[start:index] if v is not None]
    if len(prior) < 4:
        return {"had_pullback": None, "reclaim": None, "renewed_high": None}
    peak_pos = max(range(len(prior)), key=lambda j: prior[j])
    after_peak = prior[peak_pos + 1:]
    had_pullback = bool(after_peak and min(after_peak) < prior[peak_pos])
    current_close = float(closes[index])
    prior_short = prior[-min(3, len(prior)):]
    reclaim = bool(had_pullback and current_close > max(prior_short))
    prior_highs = [_num(r.get("high")) for r in bars[max(0, index - params.high_lookback):index]]
    renewed_high = None if not prior_highs or any(v is None for v in prior_highs) or highs[index] is None else bool(float(highs[index]) > max(float(v) for v in prior_highs if v is not None))
    return {"had_pullback": had_pullback, "reclaim": reclaim, "renewed_high": renewed_high}


def _topology_states(
    *,
    bars: Sequence[Mapping[str, Any]],
    index: int,
    mg: Mapping[str, Any],
    base: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    params: CandidateParams,
) -> tuple[dict[str, bool], dict[str, Any]]:
    c = mg["components"]
    b = base["states"]
    pr = _pullback_reaccel_features(bars, index, params)

    up = _is_true(c.get("UP_PATH"))
    persist = _is_true(c.get("MULTIBAR_PERSISTENCE"))
    accept = _is_true(c.get("BAR_ACCEPTANCE"))
    value = _is_true(c.get("VALUE_EXPANSION"))
    anti_stall = _is_true(c.get("ANTI_BUY_STALL"))
    fresh = _is_true(c.get("FRESH_HIGH"))
    flow = _is_true(c.get("CONSTRUCTIVE_FLOW"))
    retained = _is_true(c.get("EARLY_STRENGTH_RETAINED"))
    recovery = _is_true(b.get("F05A_SESSION_OPEN_RECOVERY"))
    late_lift = _is_true(b.get("F04B_LATE_LIFT"))

    wake_a = bool(context and context.get("activity_wake"))
    wake_r = bool(context and context.get("range_wake"))
    wake_p = bool(context and context.get("path_wake"))

    states = {
        "J01_WAKE_RESPONSE_RETENTION": wake_a and wake_p and up and persist and accept and value and anti_stall and not late_lift,
        "J02_RECOVERY_RECLAIM": recovery and accept and value and fresh and anti_stall,
        "J03_COMPRESSION_EXPANSION": wake_a and wake_r and wake_p and up and accept and value and fresh and anti_stall,
        "J04_PULLBACK_REACCELERATION": bool(pr["had_pullback"]) and bool(pr["reclaim"]) and bool(pr["renewed_high"]) and persist and accept and value and anti_stall,
        "J05_FLOW_RESILIENT_CONTINUATION": up and persist and accept and value and flow and anti_stall and fresh,
        "J06_EARLY_STRENGTH_RETAINED": wake_p and retained and persist and accept and fresh and anti_stall and not late_lift,
    }
    evidence = {
        "UP_PATH": c.get("UP_PATH"),
        "MULTIBAR_PERSISTENCE": c.get("MULTIBAR_PERSISTENCE"),
        "BAR_ACCEPTANCE": c.get("BAR_ACCEPTANCE"),
        "VALUE_EXPANSION": c.get("VALUE_EXPANSION"),
        "CONSTRUCTIVE_FLOW": c.get("CONSTRUCTIVE_FLOW"),
        "ANTI_BUY_STALL": c.get("ANTI_BUY_STALL"),
        "FRESH_HIGH": c.get("FRESH_HIGH"),
        "EARLY_STRENGTH_RETAINED": c.get("EARLY_STRENGTH_RETAINED"),
        "F05A_SESSION_OPEN_RECOVERY": b.get("F05A_SESSION_OPEN_RECOVERY"),
        "F04B_LATE_LIFT": b.get("F04B_LATE_LIFT"),
        **pr,
        "context": dict(context) if context else None,
    }
    return states, evidence


def _bucket_day_change(x: float | None) -> str:
    if x is None:
        return "UNKNOWN"
    if x < 0:
        return "NEG"
    if x < 2:
        return "0_2"
    if x < 5:
        return "2_5"
    return "GE_5"


def _bucket_activity(x: float | None) -> str:
    if x is None:
        return "UNKNOWN"
    if x < 1:
        return "LT_1"
    if x < 1.5:
        return "1_1P5"
    return "GE_1P5"


def _time_band(ts: Any) -> str:
    try:
        t = datetime.fromisoformat(str(ts)).time()
    except Exception:
        return "UNKNOWN"
    if t.hour < 10:
        return "09"
    if t.hour < 12:
        return "10_11"
    if t.hour < 14:
        return "12_13"
    return "14_PLUS"


def _blank_metric() -> dict[str, Any]:
    return {
        "candidate_count": 0,
        "qualified_count": 0,
        "evaluable_count": 0,
        "profit_count": 0,
        "loss_count": 0,
        "sum_net_pl": 0.0,
        "sum_net_mfe_pct": 0.0,
        "sum_mae_pct": 0.0,
        "sum_eod_net_pct": 0.0,
        "profit_room_reject_count": 0,
        "training_unready_count": 0,
    }


def _add_metric(m: dict[str, Any], r: Mapping[str, Any]) -> None:
    m["candidate_count"] += 1
    if r.get("training_unready"):
        m["training_unready_count"] += 1
        return
    if not r.get("profit_room_pass"):
        m["profit_room_reject_count"] += 1
        return
    m["qualified_count"] += 1
    if not r.get("evaluable"):
        return
    m["evaluable_count"] += 1
    net = float(r.get("net_pl") or 0.0)
    m["sum_net_pl"] += net
    m["profit_count"] += int(net > 0)
    m["loss_count"] += int(net < 0)
    m["sum_net_mfe_pct"] += float(r.get("net_mfe_pct") or 0.0)
    m["sum_mae_pct"] += float(r.get("mae_pct") or 0.0)
    m["sum_eod_net_pct"] += float(r.get("eod_net_pct") or 0.0)


def _final_metric(m: Mapping[str, Any]) -> dict[str, Any]:
    n = int(m["evaluable_count"])
    q = int(m["qualified_count"])
    return {
        **{k: int(m[k]) for k in ("candidate_count", "qualified_count", "evaluable_count", "profit_count", "loss_count", "profit_room_reject_count", "training_unready_count")},
        "win_rate": float(m["profit_count"]) / n if n else None,
        "loss_rate": float(m["loss_count"]) / n if n else None,
        "net_pl": float(m["sum_net_pl"]),
        "mean_net_pl": float(m["sum_net_pl"]) / n if n else None,
        "mean_net_mfe_pct": float(m["sum_net_mfe_pct"]) / n if n else None,
        "mean_mae_pct": float(m["sum_mae_pct"]) / n if n else None,
        "mean_eod_net_pct": float(m["sum_eod_net_pct"]) / n if n else None,
        "qualification_rate": q / int(m["candidate_count"]) if int(m["candidate_count"]) else None,
    }


def _evaluate_trade(
    *,
    bars: Sequence[Mapping[str, Any]],
    signal_index: int,
    reward_history: Sequence[float],
    min_training: int,
    q1: float,
    q2: float,
    capital: float,
    buy_fee_pct: float,
    sell_fee_pct: float,
) -> dict[str, Any]:
    if signal_index + 1 >= len(bars):
        return {"evaluable": False, "training_unready": len(reward_history) < min_training, "profit_room_pass": False}
    step = _observed_step(bars, signal_index)
    next_open = _num(bars[signal_index + 1].get("open"))
    if step is None or next_open is None or next_open <= 0:
        return {"evaluable": False, "training_unready": len(reward_history) < min_training, "profit_room_pass": False}
    entry = next_open + step
    future = bars[signal_index + 1:]
    highs = [_num(r.get("high")) for r in future]
    lows = [_num(r.get("low")) for r in future]
    closes = [_num(r.get("close")) for r in future]
    if not highs or any(v is None for v in highs + lows + closes):
        return {"evaluable": False, "training_unready": len(reward_history) < min_training, "profit_room_pass": False}
    high = max(float(v) for v in highs if v is not None)
    low = min(float(v) for v in lows if v is not None)
    final_close = float(closes[-1])
    high_exit = max(0.0, high - step)
    eod_exit = max(0.0, final_close - step)
    actual_net_mfe = _net_return_pct(entry, high_exit, buy_fee_pct, sell_fee_pct)
    mae_pct = (low / entry - 1.0) * 100.0
    eod_net_pct = _net_return_pct(entry, eod_exit, buy_fee_pct, sell_fee_pct)

    if len(reward_history) < min_training:
        return {
            "evaluable": True,
            "training_unready": True,
            "profit_room_pass": False,
            "entry_proxy": entry,
            "step_proxy": step,
            "net_mfe_pct": actual_net_mfe,
            "mae_pct": mae_pct,
            "eod_net_pct": eod_net_pct,
            "training_count": len(reward_history),
        }
    tq1, tq2 = _quantile(reward_history, q1), _quantile(reward_history, q2)
    if tq1 is None or tq2 is None or tq1 <= 0 or tq2 <= tq1:
        return {
            "evaluable": True,
            "training_unready": False,
            "profit_room_pass": False,
            "entry_proxy": entry,
            "step_proxy": step,
            "net_mfe_pct": actual_net_mfe,
            "mae_pct": mae_pct,
            "eod_net_pct": eod_net_pct,
            "training_count": len(reward_history),
            "historical_q1_net_mfe_pct": tq1,
            "historical_q2_net_mfe_pct": tq2,
        }

    buy_mult = 1 + buy_fee_pct / 100.0
    sell_mult = 1 - sell_fee_pct / 100.0
    tp1_exit_needed = entry * buy_mult * (1 + tq1 / 100.0) / sell_mult
    tp2_exit_needed = entry * buy_mult * (1 + tq2 / 100.0) / sell_mult
    tp1 = tp1_exit_needed + step
    tp2 = tp2_exit_needed + step
    profit_room_pass = bool(tq1 > 0 and tq2 > tq1)

    lots = int(capital // (entry * 100.0))
    if lots < 1:
        profit_room_pass = False
    shares = lots * 100
    tp1_hit = next((j for j, r in enumerate(future) if _num(r.get("high")) is not None and float(r["high"]) >= tp1), None)
    tp2_hit = next((j for j, r in enumerate(future) if _num(r.get("high")) is not None and float(r["high"]) >= tp2), None)

    net_pl = 0.0
    if profit_room_pass:
        l1 = lots // 2 or lots
        l2 = lots - l1
        if tp1_hit is not None:
            net_pl += _execution_net(entry, max(0.0, tp1 - step), l1 * 100, buy_fee_pct, sell_fee_pct)
            if l2:
                exit2 = max(0.0, tp2 - step) if tp2_hit is not None else eod_exit
                net_pl += _execution_net(entry, exit2, l2 * 100, buy_fee_pct, sell_fee_pct)
        else:
            net_pl += _execution_net(entry, eod_exit, shares, buy_fee_pct, sell_fee_pct)

    return {
        "evaluable": True,
        "training_unready": False,
        "profit_room_pass": profit_room_pass,
        "entry_proxy": entry,
        "step_proxy": step,
        "lots": lots,
        "historical_q1_net_mfe_pct": tq1,
        "historical_q2_net_mfe_pct": tq2,
        "TP-1": tp1,
        "TP-2": tp2,
        "tp1_hit": tp1_hit is not None,
        "tp2_hit": tp2_hit is not None,
        "net_mfe_pct": actual_net_mfe,
        "mae_pct": mae_pct,
        "eod_net_pct": eod_net_pct,
        "net_pl": net_pl,
        "training_count": len(reward_history),
    }


def build_behavior_topology_report(
    *,
    source_names: Sequence[str],
    params: CandidateParams,
    capital_per_entry: float,
    buy_fee_pct: float,
    sell_fee_pct: float,
    min_training_examples: int,
    tp1_quantile: float,
    tp2_quantile: float,
    prior_window: int = 2,
) -> dict[str, Any]:
    params.validate()
    if not source_names:
        raise ValueError("SOURCE_NAMES_REQUIRED")
    if not (0 < tp1_quantile < tp2_quantile < 1):
        raise ValueError("TARGET_QUANTILES_INVALID")

    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_dates: list[str] = []
    seen_dates: set[str] = set()
    current_date: str | None = None
    reward_history: dict[str, list[float]] = {t: [] for t in TOPOLOGIES}
    staged_rewards: dict[str, list[float]] = {t: [] for t in TOPOLOGIES}

    aggregate = {src: {t: _blank_metric() for t in TOPOLOGIES} for src in source_names}
    daily: dict[str, dict[str, dict[str, Any]]] = {src: defaultdict(lambda: {t: _blank_metric() for t in TOPOLOGIES}) for src in source_names}
    condition: dict[str, dict[str, dict[str, Any]]] = {t: defaultdict(_blank_metric) for t in TOPOLOGIES}
    examples: dict[str, list[dict[str, Any]]] = {t: [] for t in TOPOLOGIES}
    packet_counts: dict[str, int] = {}
    row_counts: dict[str, int] = {}

    def close_market_date(date_to_close: str | None) -> None:
        if date_to_close is None or date_to_close in seen_dates:
            return
        completed_dates.append(date_to_close)
        seen_dates.add(date_to_close)
        for t in TOPOLOGIES:
            reward_history[t].extend(staged_rewards[t])
            staged_rewards[t].clear()
        keep = set(completed_dates[-(prior_window + 2):])
        for ticker in list(history):
            history[ticker] = {d: r for d, r in history[ticker].items() if d in keep}
            if not history[ticker]:
                del history[ticker]

    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        pc = rc = 0
        for _manifest_row, packet in reader.iter_packets():
            date = str(packet.identity.trading_date)
            if current_date is None:
                current_date = date
            elif date != current_date:
                close_market_date(current_date)
                current_date = date

            all_bars, _ = packet_to_formula_bars(packet)
            bars = [b for b in all_bars if b.get("session_eligible")]
            pc += 1
            rc += len(all_bars)
            if not bars:
                continue
            ticker = str(packet.identity.ticker)
            ticker_hist = history.get(ticker, {})
            prior_dates = completed_dates[-prior_window:] if len(completed_dates) >= prior_window else []
            previous_close = _previous_regular_close(ticker_hist, prior_dates)
            mg_rows = evaluate_mg_packet(bars, params)
            base_rows = evaluate_intraday_candidates(bars, params)
            first_seen: set[str] = set()

            for i, (mg, base) in enumerate(zip(mg_rows, base_rows, strict=True)):
                if not mg.get("publication_slot"):
                    continue
                context = None
                if len(prior_dates) == prior_window:
                    context = _history_context(bars=bars, index=i, history_by_date=ticker_hist, prior_dates=prior_dates)
                states, evidence = _topology_states(bars=bars, index=i, mg=mg, base=base, context=context, params=params)
                signal_price = _num(bars[i].get("close"))
                if signal_price is None or signal_price <= 0:
                    continue
                day_chg = ((signal_price / previous_close - 1) * 100.0) if previous_close else None

                for topo, matched in states.items():
                    if not matched or topo in first_seen:
                        continue
                    first_seen.add(topo)
                    r = _evaluate_trade(
                        bars=bars,
                        signal_index=i,
                        reward_history=reward_history[topo],
                        min_training=min_training_examples,
                        q1=tp1_quantile,
                        q2=tp2_quantile,
                        capital=capital_per_entry,
                        buy_fee_pct=buy_fee_pct,
                        sell_fee_pct=sell_fee_pct,
                    )
                    if r.get("evaluable") and r.get("net_mfe_pct") is not None:
                        staged_rewards[topo].append(float(r["net_mfe_pct"]))

                    r = {
                        **r,
                        "source": source_name,
                        "trading_date": date,
                        "ticker": ticker,
                        "timestamp": mg.get("timestamp"),
                        "signal_price": signal_price,
                        "day_change_pct": day_chg,
                        "evidence": evidence,
                    }
                    _add_metric(aggregate[source_name][topo], r)
                    _add_metric(daily[source_name][date][topo], r)
                    ctx = evidence.get("context") or {}
                    condition_key = "|".join((
                        f"SEG={ctx.get('session_segment', 'UNKNOWN')}",
                        f"TIME={_time_band(mg.get('timestamp'))}",
                        f"CHG={_bucket_day_change(day_chg)}",
                        f"ACT={_bucket_activity(_num(ctx.get('activity_ratio')))}",
                    ))
                    _add_metric(condition[topo][condition_key], r)
                    if len(examples[topo]) < 30:
                        examples[topo].append(r)

            history.setdefault(ticker, {})[date] = DayRecord(trading_date=date, bars=tuple(dict(b) for b in bars))
        packet_counts[source_name] = pc
        row_counts[source_name] = rc

    close_market_date(current_date)

    agg_f = {s: {t: _final_metric(m) for t, m in d.items()} for s, d in aggregate.items()}
    daily_f = {s: {d: {t: _final_metric(m) for t, m in x.items()} for d, x in sorted(days.items())} for s, days in daily.items()}
    cond_f = {t: {k: _final_metric(m) for k, m in sorted(v.items())} for t, v in condition.items()}

    stability: dict[str, Any] = {}
    for topo in TOPOLOGIES:
        rows = [agg_f[s][topo] for s in source_names]
        eval_rows = [r for r in rows if r["evaluable_count"] > 0]
        wins = [r["win_rate"] for r in eval_rows if r["win_rate"] is not None]
        means = [r["mean_net_pl"] for r in eval_rows if r["mean_net_pl"] is not None]
        stability[topo] = {
            "period_count": len(eval_rows),
            "total_candidates": sum(r["candidate_count"] for r in rows),
            "total_qualified": sum(r["qualified_count"] for r in rows),
            "total_evaluable": sum(r["evaluable_count"] for r in rows),
            "total_net_pl": sum(r["net_pl"] for r in rows),
            "min_period_win_rate": min(wins) if wins else None,
            "median_period_win_rate": float(median(wins)) if wins else None,
            "min_period_mean_net_pl": min(means) if means else None,
            "median_period_mean_net_pl": float(median(means)) if means else None,
            "training_examples_final": len(reward_history[topo]),
        }

    ranking = sorted(
        TOPOLOGIES,
        key=lambda t: (
            -1 if stability[t]["min_period_win_rate"] is None else stability[t]["min_period_win_rate"],
            -1e99 if stability[t]["total_net_pl"] is None else stability[t]["total_net_pl"],
            stability[t]["total_evaluable"],
        ),
        reverse=True,
    )

    return {
        "schema": "A1_TELEGRAM_MG_BEHAVIOR_TOPOLOGY_V2",
        "status": "RESEARCH_CANDIDATE_NOT_CANONICAL",
        "objective": "COMPARE_DISTINCT_BEHAVIOR_TOPOLOGIES_ACROSS_ALL_AVAILABLE_DEVELOPMENT_MONTHS_WITH_POST_SIGNAL_EXECUTION_AND_PRIOR_ONLY_PROFIT_ROOM",
        "source_names": list(source_names),
        "topologies": list(TOPOLOGIES),
        "formula_change_policy": "WHEN_TOPOLOGY_IS_STRUCTURALLY_WEAK_REPLACE_COMPONENT_COMBINATION;DO_NOT_RESCUE_BY_THRESHOLD_TUNING_ONLY",
        "execution_policy": "SIGNAL_AT_PUBLICATION_SLOT__ENTRY_NEXT_ELIGIBLE_BAR_OPEN_PLUS_CAUSAL_STEP_PROXY__EXIT_TARGET_MINUS_STEP_OR_EOD__FEES_INCLUDED",
        "profit_room_policy": "TOPOLOGY_SPECIFIC_PRIOR_COMPLETED_DATES_ONLY_NET_MFE_QUANTILES",
        "target_quantiles": [tp1_quantile, tp2_quantile],
        "min_training_examples": min_training_examples,
        "prior_window": prior_window,
        "aggregate": agg_f,
        "daily": daily_f,
        "condition_breakdown": cond_f,
        "cross_period_stability": stability,
        "research_ranking": ranking,
        "samples": examples,
        "source_packet_counts": packet_counts,
        "source_row_counts": row_counts,
        "future_data_used_for_signal_state": False,
        "same_date_future_used_for_profit_gate": False,
        "future_data_used_for_outcome_and_next_date_training_only": True,
        "h_plus_1_used": False,
        "notes": [
            "No old MG_B/P5/ARP_STRONG gate is required by the new topology engine.",
            "Topologies are different component structures, not numeric threshold variants.",
            "Historical observed-step is an execution proxy only; it is not claimed as actual BBO/queue/fill.",
            "March 2025 remains untouched OOS and is not part of this development comparison.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-telegram-mg-behavior-topology-v2")
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--software-revision", required=True)
    p.add_argument("--drive-output-folder-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--capital-per-entry", type=float, required=True)
    p.add_argument("--buy-fee-pct", type=float, required=True)
    p.add_argument("--sell-fee-pct", type=float, required=True)
    p.add_argument("--min-training-examples", type=int, default=30)
    p.add_argument("--tp1-quantile", type=float, default=0.25)
    p.add_argument("--tp2-quantile", type=float, default=0.50)
    p.add_argument("--prior-window", type=int, default=2)
    p.add_argument("--effort-lookback", type=int, required=True)
    p.add_argument("--progress-lookback", type=int, required=True)
    p.add_argument("--high-lookback", type=int, required=True)
    p.add_argument("--recovery-lookback", type=int, required=True)
    p.add_argument("--low-stabilization-bars", type=int, required=True)
    p.add_argument("--early-checkpoint-bar", type=int, required=True)
    p.add_argument("--late-lift-min-bar", type=int, required=True)
    a = p.parse_args(argv)
    params = CandidateParams(
        effort_lookback=a.effort_lookback,
        progress_lookback=a.progress_lookback,
        high_lookback=a.high_lookback,
        recovery_lookback=a.recovery_lookback,
        low_stabilization_bars=a.low_stabilization_bars,
        early_checkpoint_bar=a.early_checkpoint_bar,
        late_lift_min_bar=a.late_lift_min_bar,
    )
    report = build_behavior_topology_report(
        source_names=a.source_name,
        params=params,
        capital_per_entry=a.capital_per_entry,
        buy_fee_pct=a.buy_fee_pct,
        sell_fee_pct=a.sell_fee_pct,
        min_training_examples=a.min_training_examples,
        tp1_quantile=a.tp1_quantile,
        tp2_quantile=a.tp2_quantile,
        prior_window=a.prior_window,
    )
    report = {**report, "request_id": a.request_id, "software_revision": a.software_revision}
    Path(a.output).write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, a.drive_output_folder_id)
    safe = "".join(ch for ch in a.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_BEHAVIOR_TOPOLOGY_V2__{safe}.json", obj=report)
    print(dumps({"pass": True, "drive_artifact": uploaded, "ranking": report["research_ranking"], "stability": report["cross_period_stability"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
