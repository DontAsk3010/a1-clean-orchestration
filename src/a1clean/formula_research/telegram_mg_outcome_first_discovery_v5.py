from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
from json import dumps
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .comparable_context_cache import build_history_context_series
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, evaluate_intraday_candidates
from .telegram_mg_behavior_topology_v2 import _is_true, _num, _observed_step, _net_return_pct, _topology_states
from .telegram_mg_multiday_context_study import DayRecord
from .telegram_mg_replay import evaluate_mg_packet
from .telegram_mg_sequence_discovery_v4 import _snapshot, sequence_markers


def _q(values: Sequence[float], p: float) -> float | None:
    vals = sorted(float(v) for v in values)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    w = pos - lo
    return vals[lo] * (1 - w) + vals[hi] * w


def _metric(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evals = [r for r in rows if r.get("evaluable") and r.get("net_mfe_pct") is not None]
    mfe = [float(r["net_mfe_pct"]) for r in evals]
    mae = [float(r["mae_pct"]) for r in evals if r.get("mae_pct") is not None]
    eod = [float(r["eod_net_pct"]) for r in evals if r.get("eod_net_pct") is not None]
    return {
        "candidate_count": len(rows),
        "evaluable_count": len(evals),
        "positive_net_mfe_rate": (sum(v > 0 for v in mfe) / len(mfe)) if mfe else None,
        "net_mfe_q10": _q(mfe, 0.10),
        "net_mfe_q25": _q(mfe, 0.25),
        "net_mfe_q50": _q(mfe, 0.50),
        "net_mfe_q75": _q(mfe, 0.75),
        "net_mfe_q90": _q(mfe, 0.90),
        "mae_q50": _q(mae, 0.50),
        "eod_positive_rate": (sum(v > 0 for v in eod) / len(eod)) if eod else None,
        "eod_q50": _q(eod, 0.50),
    }


def _session_band(timestamp: Any) -> str | None:
    text = str(timestamp or "")
    try:
        hhmm = text.split("T", 1)[1][:5]
        hh, mm = [int(x) for x in hhmm.split(":")]
    except Exception:
        return None
    minutes = hh * 60 + mm
    if minutes < 10 * 60:
        return "TIME_09"
    if minutes < 12 * 60:
        return "TIME_10_11"
    if minutes < 14 * 60:
        return "TIME_12_13"
    return "TIME_14_PLUS"


def _markers(
    *, mg: Mapping[str, Any], base: Mapping[str, Any], states: Mapping[str, bool], evidence: Mapping[str, Any],
    prior_publications: Sequence[Mapping[str, bool]],
) -> tuple[tuple[str, ...], dict[str, bool]]:
    snap = _snapshot(mg=mg, base=base, evidence=evidence)
    out = set(sequence_markers(snap, prior_publications))
    c = mg["components"]
    b = base["states"]
    current = {
        "CUR_UP": _is_true(c.get("UP_PATH")),
        "CUR_PERSIST": _is_true(c.get("MULTIBAR_PERSISTENCE")),
        "CUR_ACCEPT": _is_true(c.get("BAR_ACCEPTANCE")),
        "CUR_VALUE": _is_true(c.get("VALUE_EXPANSION")),
        "CUR_FLOW": _is_true(c.get("CONSTRUCTIVE_FLOW")),
        "CUR_ANTI_STALL": _is_true(c.get("ANTI_BUY_STALL")),
        "CUR_FRESH": _is_true(c.get("FRESH_HIGH")),
        "CUR_RETAINED": _is_true(c.get("EARLY_STRENGTH_RETAINED")),
        "CUR_RECOVERY": _is_true(b.get("F05A_SESSION_OPEN_RECOVERY")),
        "CUR_NOT_LATE_LIFT": not _is_true(b.get("F04B_LATE_LIFT")),
        "CUR_PULLBACK": bool(evidence.get("had_pullback")),
        "CUR_RECLAIM": bool(evidence.get("reclaim")),
        "CUR_RENEWED_HIGH": bool(evidence.get("renewed_high")),
    }
    for key, value in current.items():
        if value:
            out.add(key)
    for key, value in states.items():
        if value:
            out.add(key)
    band = _session_band(mg.get("timestamp"))
    if band:
        out.add(band)
    return tuple(sorted(out)), snap


def _outcome_at(
    bars: Sequence[Mapping[str, Any]], signal_index: int, buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    if signal_index + 1 >= len(bars):
        return {"evaluable": False}
    step = _observed_step(bars, signal_index)
    next_open = _num(bars[signal_index + 1].get("open"))
    if step is None or next_open is None or next_open <= 0:
        return {"evaluable": False}
    entry = float(next_open) + float(step)
    future = bars[signal_index + 1:]
    highs = [_num(r.get("high")) for r in future]
    lows = [_num(r.get("low")) for r in future]
    closes = [_num(r.get("close")) for r in future]
    if not future or any(v is None for v in highs + lows + closes):
        return {"evaluable": False}
    high = max(float(v) for v in highs if v is not None)
    low = min(float(v) for v in lows if v is not None)
    final_close = float(closes[-1])
    high_exit = max(0.0, high - float(step))
    eod_exit = max(0.0, final_close - float(step))
    return {
        "evaluable": True,
        "entry_proxy": entry,
        "step_proxy": float(step),
        "net_mfe_pct": _net_return_pct(entry, high_exit, buy_fee_pct, sell_fee_pct),
        "mae_pct": (low / entry - 1.0) * 100.0,
        "eod_net_pct": _net_return_pct(entry, eod_exit, buy_fee_pct, sell_fee_pct),
    }


def choose_discovery_representative(events: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    evals = [e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    if not evals:
        return None
    for event in evals:
        if float(event["net_mfe_pct"]) > 0:
            return event
    return max(evals, key=lambda e: float(e["net_mfe_pct"]))


def _sig_id(parts: Sequence[str]) -> str:
    return " & ".join(sorted(parts))


def _mine_signatures(
    reps: Sequence[Mapping[str, Any]], *, min_support: int, top_marker_limit: int, top_signature_limit: int,
    max_signature_size: int,
) -> tuple[list[tuple[str, tuple[str, ...], dict[str, Any]]], dict[str, Any]]:
    evals = [r for r in reps if r.get("evaluable") and r.get("net_mfe_pct") is not None]
    base_rate = (sum(float(r["net_mfe_pct"]) > 0 for r in evals) / len(evals)) if evals else 0.0
    marker_universe = sorted({m for r in evals for m in r.get("markers", [])})
    marker_rows: list[tuple[str, dict[str, Any]]] = []
    for marker in marker_universe:
        rows = [r for r in evals if marker in r.get("markers", [])]
        m = _metric(rows)
        if m["evaluable_count"] >= min_support and m["positive_net_mfe_rate"] is not None and m["positive_net_mfe_rate"] > base_rate:
            marker_rows.append((marker, m))
    marker_rows.sort(key=lambda x: (
        float(x[1]["positive_net_mfe_rate"] or 0) - base_rate,
        float(x[1]["net_mfe_q50"] or -999),
        int(x[1]["evaluable_count"]),
    ), reverse=True)
    top_markers = [m for m, _ in marker_rows[:top_marker_limit]]

    candidates: list[tuple[str, tuple[str, ...], dict[str, Any]]] = []
    for size in range(1, max_signature_size + 1):
        for parts in combinations(top_markers, size):
            rows = [r for r in evals if all(p in r.get("markers", []) for p in parts)]
            m = _metric(rows)
            if m["evaluable_count"] < min_support:
                continue
            rate = m["positive_net_mfe_rate"]
            med = m["net_mfe_q50"]
            if rate is None or rate <= base_rate or med is None or med <= 0:
                continue
            candidates.append((_sig_id(parts), tuple(parts), m))
    candidates.sort(key=lambda x: (
        float(x[2]["positive_net_mfe_rate"] or 0) - base_rate,
        float(x[2]["net_mfe_q25"] or -999),
        float(x[2]["net_mfe_q50"] or -999),
        int(x[2]["evaluable_count"]),
    ), reverse=True)
    return candidates[:top_signature_limit], {
        "representative_count": len(evals),
        "representative_positive_rate": base_rate,
        "marker_universe_count": len(marker_universe),
        "top_markers": [{"marker": m, "metric": metric} for m, metric in marker_rows[:top_marker_limit]],
    }


def _iter_packet_events(
    *, bars: Sequence[Mapping[str, Any]], context_series: Sequence[Mapping[str, Any] | None], params: CandidateParams,
    buy_fee_pct: float, sell_fee_pct: float,
) -> list[dict[str, Any]]:
    mg_rows = evaluate_mg_packet(bars, params)
    base_rows = evaluate_intraday_candidates(bars, params)
    publication_snapshots: list[dict[str, bool]] = []
    events: list[dict[str, Any]] = []
    for i, (mg, base) in enumerate(zip(mg_rows, base_rows, strict=True)):
        states, evidence = _topology_states(
            bars=bars, index=i, mg=mg, base=base, context=context_series[i], params=params
        )
        if not mg.get("publication_slot"):
            continue
        markers, snap = _markers(
            mg=mg, base=base, states=states, evidence=evidence, prior_publications=publication_snapshots
        )
        outcome = _outcome_at(bars, i, buy_fee_pct, sell_fee_pct)
        events.append({
            **outcome,
            "timestamp": mg.get("timestamp"),
            "signal_index": i,
            "signal_price": _num(bars[i].get("close")),
            "markers": markers,
        })
        publication_snapshots.append(snap)
    return events


def _scan_source(
    *, source_names: Sequence[str], params: CandidateParams, prior_window: int,
    buy_fee_pct: float, sell_fee_pct: float,
    candidate_parts: Mapping[str, tuple[str, ...]] | None = None,
    discovery_only: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, int]]:
    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_dates: list[str] = []
    seen_dates: set[str] = set()
    current_date: str | None = None
    matched_rows: dict[str, list[dict[str, Any]]] = {s: [] for s in candidate_parts or {}}
    reps: list[dict[str, Any]] = []
    packet_counts: dict[str, int] = {}

    def close_date(d: str | None) -> None:
        if d is None or d in seen_dates:
            return
        completed_dates.append(d)
        seen_dates.add(d)
        keep = set(completed_dates[-(prior_window + 2):])
        for ticker in list(history):
            history[ticker] = {k: v for k, v in history[ticker].items() if k in keep}
            if not history[ticker]:
                del history[ticker]

    anchors: dict[str, list[str]] = defaultdict(list)
    if candidate_parts:
        for sig, parts in candidate_parts.items():
            if parts:
                anchors[parts[0]].append(sig)

    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        pc = 0
        for _manifest_row, packet in reader.iter_packets():
            date = str(packet.identity.trading_date)
            if current_date is None:
                current_date = date
            elif date != current_date:
                close_date(current_date)
                current_date = date
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [b for b in all_bars if b.get("session_eligible")]
            pc += 1
            if not bars:
                continue
            ticker = str(packet.identity.ticker)
            prior_dates = completed_dates[-prior_window:] if len(completed_dates) >= prior_window else []
            if len(prior_dates) == prior_window:
                context_series = build_history_context_series(
                    bars=bars, history_by_date=history.get(ticker, {}), prior_dates=prior_dates
                )
            else:
                context_series = [None] * len(bars)
            events = _iter_packet_events(
                bars=bars, context_series=context_series, params=params,
                buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            )
            if discovery_only:
                rep = choose_discovery_representative(events)
                if rep is not None:
                    reps.append({**rep, "source": source_name, "trading_date": date, "ticker": ticker})
            elif candidate_parts:
                seen_sig: set[str] = set()
                for event in events:
                    marker_set = set(event.get("markers", ()))
                    possible: set[str] = set()
                    for marker in marker_set:
                        possible.update(anchors.get(marker, ()))
                    for sig in possible:
                        if sig in seen_sig:
                            continue
                        parts = candidate_parts[sig]
                        if all(p in marker_set for p in parts):
                            seen_sig.add(sig)
                            matched_rows[sig].append({
                                **event, "source": source_name, "trading_date": date, "ticker": ticker
                            })
            history.setdefault(ticker, {})[date] = DayRecord(trading_date=date, bars=tuple(dict(b) for b in bars))
        packet_counts[source_name] = pc
    close_date(current_date)
    return matched_rows, reps, packet_counts


def build_report(
    *, source_names: Sequence[str], params: CandidateParams, prior_window: int,
    buy_fee_pct: float, sell_fee_pct: float, discovery_min_support: int,
    validation_min_support: int, max_signature_size: int, top_marker_limit: int,
    top_signature_limit: int,
) -> dict[str, Any]:
    if len(source_names) < 3:
        raise ValueError("V5_REQUIRES_DISCOVERY_PLUS_TWO_VALIDATION_PERIODS")
    if max_signature_size < 1 or max_signature_size > 3:
        raise ValueError("MAX_SIGNATURE_SIZE_MUST_BE_1_TO_3")
    params.validate()
    discovery_source = source_names[0]
    _, reps, discovery_packets = _scan_source(
        source_names=[discovery_source], params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct, discovery_only=True,
    )
    candidates, discovery_summary = _mine_signatures(
        reps, min_support=discovery_min_support, top_marker_limit=top_marker_limit,
        top_signature_limit=top_signature_limit, max_signature_size=max_signature_size,
    )
    candidate_parts = {sig: parts for sig, parts, _ in candidates}
    matched, _, packet_counts = _scan_source(
        source_names=source_names, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct, candidate_parts=candidate_parts,
    )

    by_sig_period: dict[str, dict[str, list[dict[str, Any]]]] = {
        sig: {s: [] for s in source_names} for sig in candidate_parts
    }
    for sig, rows in matched.items():
        for row in rows:
            by_sig_period[sig][str(row["source"])].append(row)

    candidate_table: list[dict[str, Any]] = []
    cross_period_passed: list[str] = []
    strict_q25_passed: list[str] = []
    for sig, parts, discovery_metric in candidates:
        metrics = {s: _metric(by_sig_period[sig][s]) for s in source_names}
        passes = True
        strict = True
        for s in source_names[1:]:
            m = metrics[s]
            if m["evaluable_count"] < validation_min_support or m["positive_net_mfe_rate"] is None or m["net_mfe_q50"] is None:
                passes = False
                strict = False
                continue
            if m["positive_net_mfe_rate"] <= 0.5 or m["net_mfe_q50"] <= 0:
                passes = False
            if m["net_mfe_q25"] is None or m["net_mfe_q25"] <= 0:
                strict = False
        if passes:
            cross_period_passed.append(sig)
        if passes and strict:
            strict_q25_passed.append(sig)
        q25s = [float(metrics[s]["net_mfe_q25"]) for s in source_names if metrics[s]["net_mfe_q25"] is not None]
        meds = [float(metrics[s]["net_mfe_q50"]) for s in source_names if metrics[s]["net_mfe_q50"] is not None]
        rates = [float(metrics[s]["positive_net_mfe_rate"]) for s in source_names if metrics[s]["positive_net_mfe_rate"] is not None]
        candidate_table.append({
            "signature": sig,
            "parts": list(parts),
            "discovery_representative_metric": discovery_metric,
            "first_causal_match_by_period": metrics,
            "cross_period_pass": passes,
            "strict_q25_cross_period_pass": passes and strict,
            "min_period_q25_net_mfe": min(q25s) if q25s else None,
            "min_period_median_net_mfe": min(meds) if meds else None,
            "min_period_positive_rate": min(rates) if rates else None,
            "total_evaluable": sum(int(metrics[s]["evaluable_count"]) for s in source_names),
        })
    candidate_table.sort(key=lambda r: (
        bool(r["strict_q25_cross_period_pass"]), bool(r["cross_period_pass"]),
        float(r["min_period_positive_rate"] or -1), float(r["min_period_q25_net_mfe"] or -999),
        float(r["min_period_median_net_mfe"] or -999), int(r["total_evaluable"]),
    ), reverse=True)

    return {
        "schema": "A1_TELEGRAM_MG_OUTCOME_FIRST_DISCOVERY_V5",
        "status": "RESEARCH_CANDIDATE_NOT_CANONICAL",
        "method": "FULL_UNIVERSE_OUTCOME_LABEL_BACKWARD_CAUSAL_FINGERPRINT_MINING",
        "source_names": list(source_names),
        "discovery_source": discovery_source,
        "validation_sources": list(source_names[1:]),
        "discovery_policy": "ONE_REPRESENTATIVE_PER_TICKER_DAY__EARLIEST_POSITIVE_NET_MFE_ELSE_BEST_FAILURE__USED_FOR_DISCOVERY_LABEL_ONLY",
        "validation_policy": "EXACT_SIGNATURE__FIRST_CAUSAL_PUBLICATION_MATCH_PER_TICKER_DAY__NO_OUTCOME_BASED_SIGNAL_SELECTION",
        "discovery_summary": discovery_summary,
        "discovery_packet_counts": discovery_packets,
        "validation_packet_counts": packet_counts,
        "candidate_count": len(candidate_table),
        "cross_period_pass_count": len(cross_period_passed),
        "strict_q25_cross_period_pass_count": len(strict_q25_passed),
        "cross_period_passed_signatures": cross_period_passed[:100],
        "strict_q25_cross_period_passed_signatures": strict_q25_passed[:100],
        "candidate_table": candidate_table[:100],
        "future_data_used_for_formula_state": False,
        "future_data_used_for_discovery_label_only": True,
        "signal_entry_separation": "SIGNAL_AT_PUBLICATION_SLOT__ENTRY_NEXT_ELIGIBLE_BAR_OPEN_PLUS_CAUSAL_OBSERVED_STEP_PROXY",
        "h_plus_1_used": False,
        "march_2025_oos_touched": False,
        "parent_formula_required": False,
        "change_policy": "NO_FAILED_PARENT_GATE;OUTCOME_FIRST_FULL_UNIVERSE_DISCOVERY;FIX_SIGNATURE_BEFORE_JAN_FEB_VALIDATION",
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-telegram-mg-outcome-first-discovery-v5")
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--software-revision", required=True)
    p.add_argument("--drive-output-folder-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prior-window", type=int, default=2)
    p.add_argument("--buy-fee-pct", type=float, required=True)
    p.add_argument("--sell-fee-pct", type=float, required=True)
    p.add_argument("--discovery-min-support", type=int, required=True)
    p.add_argument("--validation-min-support", type=int, required=True)
    p.add_argument("--max-signature-size", type=int, required=True)
    p.add_argument("--top-marker-limit", type=int, required=True)
    p.add_argument("--top-signature-limit", type=int, required=True)
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
    report = build_report(
        source_names=a.source_name, params=params, prior_window=a.prior_window,
        buy_fee_pct=a.buy_fee_pct, sell_fee_pct=a.sell_fee_pct,
        discovery_min_support=a.discovery_min_support,
        validation_min_support=a.validation_min_support,
        max_signature_size=a.max_signature_size,
        top_marker_limit=a.top_marker_limit,
        top_signature_limit=a.top_signature_limit,
    )
    report = {**report, "request_id": a.request_id, "software_revision": a.software_revision}
    Path(a.output).write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, a.drive_output_folder_id)
    safe = "".join(ch for ch in a.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_OUTCOME_FIRST_DISCOVERY_V5__{safe}.json", obj=report)
    print(dumps({
        "pass": True,
        "drive_artifact": uploaded,
        "candidate_count": report["candidate_count"],
        "cross_period_pass_count": report["cross_period_pass_count"],
        "strict_q25_cross_period_pass_count": report["strict_q25_cross_period_pass_count"],
        "top_candidates": report["candidate_table"][:10],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
