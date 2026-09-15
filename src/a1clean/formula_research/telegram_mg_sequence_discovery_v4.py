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
from .telegram_mg_behavior_topology_v2 import _evaluate_trade, _is_true, _num, _topology_states
from .telegram_mg_multiday_context_study import DayRecord
from .telegram_mg_replay import evaluate_mg_packet
from .telegram_mg_structural_discovery_v3 import _derived, _metric

PARENT = "K06_EARLY_RETAINED_FLOW"
SEQUENCE_KEYS = (
    "FLOW",
    "FRESH",
    "VALUE",
    "RETAINED",
    "RECOVERY",
    "PULLBACK",
    "RECLAIM",
    "RENEWED_HIGH",
)
CONTEXT_KEYS = ("WAKE_ACTIVITY", "WAKE_RANGE", "WAKE_PATH")


def _snapshot(
    *,
    mg: Mapping[str, Any],
    base: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, bool]:
    c = mg["components"]
    b = base["states"]
    context = evidence.get("context") or {}
    return {
        "FLOW": _is_true(c.get("CONSTRUCTIVE_FLOW")),
        "FRESH": _is_true(c.get("FRESH_HIGH")),
        "VALUE": _is_true(c.get("VALUE_EXPANSION")),
        "RETAINED": _is_true(c.get("EARLY_STRENGTH_RETAINED")),
        "RECOVERY": _is_true(b.get("F05A_SESSION_OPEN_RECOVERY")),
        "PULLBACK": bool(evidence.get("had_pullback")),
        "RECLAIM": bool(evidence.get("reclaim")),
        "RENEWED_HIGH": bool(evidence.get("renewed_high")),
        "WAKE_ACTIVITY": bool(context.get("activity_wake")),
        "WAKE_RANGE": bool(context.get("range_wake")),
        "WAKE_PATH": bool(context.get("path_wake")),
    }


def sequence_markers(
    current: Mapping[str, bool], prior_publications: Sequence[Mapping[str, bool]]
) -> tuple[str, ...]:
    """Causal structural markers from publication snapshots before current.

    No numeric trading threshold is introduced here. Markers distinguish whether
    a behavior is newly present, retained, regained, or preceded by another
    behavior in the immediately preceding Telegram observation path.
    """
    prev = prior_publications[-1] if prior_publications else {}
    prev2 = prior_publications[-2] if len(prior_publications) >= 2 else {}
    older = prior_publications[:-1]
    out: set[str] = set()

    for key in SEQUENCE_KEYS:
        cur = bool(current.get(key))
        p1 = bool(prev.get(key))
        p2 = bool(prev2.get(key))
        older_seen = any(bool(row.get(key)) for row in older)
        if cur and not p1:
            out.add(f"NEW_{key}")
        if cur and p1:
            out.add(f"HELD_{key}")
        if cur and p1 and p2:
            out.add(f"HELD2_{key}")
        if cur and not p1 and older_seen:
            out.add(f"REGAIN_{key}")
        if p1:
            out.add(f"PREV_{key}")
        if any(bool(row.get(key)) for row in prior_publications[-3:]):
            out.add(f"PRIOR3_{key}")

    for key in CONTEXT_KEYS:
        if bool(current.get(key)):
            out.add(key)

    return tuple(sorted(out))


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


def _signature_metric(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    evals = [r for r in rows if r.get("evaluable") and r.get("net_mfe_pct") is not None]
    mfe = [float(r["net_mfe_pct"]) for r in evals]
    eod = [float(r["eod_net_pct"]) for r in evals if r.get("eod_net_pct") is not None]
    mae = [float(r["mae_pct"]) for r in evals if r.get("mae_pct") is not None]
    return {
        "candidate_count": len(rows),
        "evaluable_count": len(evals),
        "positive_net_mfe_rate": (sum(v > 0 for v in mfe) / len(mfe)) if mfe else None,
        "net_mfe_q10": _q(mfe, 0.10),
        "net_mfe_q25": _q(mfe, 0.25),
        "net_mfe_q50": _q(mfe, 0.50),
        "net_mfe_q75": _q(mfe, 0.75),
        "eod_positive_rate": (sum(v > 0 for v in eod) / len(eod)) if eod else None,
        "eod_q50": _q(eod, 0.50),
        "mae_q50": _q(mae, 0.50),
        "mae_q75": _q(mae, 0.75),
    }


def _sig_id(parts: Sequence[str]) -> str:
    return " & ".join(sorted(parts))


def build_report(
    *,
    source_names: Sequence[str],
    params: CandidateParams,
    prior_window: int,
    buy_fee_pct: float,
    sell_fee_pct: float,
    discovery_min_support: int,
    validation_min_support: int,
    max_signature_size: int,
) -> dict[str, Any]:
    if len(source_names) < 3:
        raise ValueError("V4_REQUIRES_DISCOVERY_PLUS_TWO_VALIDATION_PERIODS")
    if max_signature_size < 1 or max_signature_size > 3:
        raise ValueError("MAX_SIGNATURE_SIZE_MUST_BE_1_TO_3")
    params.validate()

    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_dates: list[str] = []
    seen_dates: set[str] = set()
    current_date: str | None = None
    parent_rows: dict[str, list[dict[str, Any]]] = {s: [] for s in source_names}
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
                    bars=bars,
                    history_by_date=history.get(ticker, {}),
                    prior_dates=prior_dates,
                )
            else:
                context_series = [None] * len(bars)

            mg_rows = evaluate_mg_packet(bars, params)
            base_rows = evaluate_intraday_candidates(bars, params)
            state_rows: list[dict[str, bool]] = []
            publication_snapshots: list[dict[str, bool]] = []
            parent_seen = False

            for i, (mg, base) in enumerate(zip(mg_rows, base_rows, strict=True)):
                states, evidence = _topology_states(
                    bars=bars,
                    index=i,
                    mg=mg,
                    base=base,
                    context=context_series[i],
                    params=params,
                )
                state_rows.append(states)
                if not mg.get("publication_slot"):
                    continue

                snap = _snapshot(mg=mg, base=base, evidence=evidence)
                recent = state_rows[max(0, i - 5):i]
                formulas = _derived(states, recent)
                matched_parent = bool(formulas.get(PARENT))

                if matched_parent and not parent_seen:
                    parent_seen = True
                    markers = sequence_markers(snap, publication_snapshots)
                    outcome = _evaluate_trade(
                        bars=bars,
                        signal_index=i,
                        reward_history=(),
                        min_training=10**9,
                        q1=0.25,
                        q2=0.50,
                        capital=5_000_000,
                        buy_fee_pct=buy_fee_pct,
                        sell_fee_pct=sell_fee_pct,
                    )
                    parent_rows[source_name].append({
                        **outcome,
                        "source": source_name,
                        "trading_date": date,
                        "ticker": ticker,
                        "timestamp": mg.get("timestamp"),
                        "signal_price": _num(bars[i].get("close")),
                        "markers": list(markers),
                        "base_paths": [k for k, v in states.items() if v],
                    })

                publication_snapshots.append(snap)

            history.setdefault(ticker, {})[date] = DayRecord(
                trading_date=date, bars=tuple(dict(b) for b in bars)
            )
        packet_counts[source_name] = pc
    close_date(current_date)

    discovery_source = source_names[0]
    discovery_rows = parent_rows[discovery_source]
    signatures: dict[str, tuple[str, ...]] = {}
    for row in discovery_rows:
        markers = tuple(sorted(set(str(x) for x in row.get("markers", []))))
        for size in range(1, min(max_signature_size, len(markers)) + 1):
            for parts in combinations(markers, size):
                signatures.setdefault(_sig_id(parts), tuple(parts))

    discovery_metrics: dict[str, dict[str, Any]] = {}
    eligible: list[str] = []
    for sig, parts in signatures.items():
        rows = [r for r in discovery_rows if all(p in r.get("markers", []) for p in parts)]
        m = _signature_metric(rows)
        if m["evaluable_count"] >= discovery_min_support:
            discovery_metrics[sig] = m
            if m["net_mfe_q25"] is not None and m["net_mfe_q25"] > 0:
                eligible.append(sig)

    validation: dict[str, dict[str, dict[str, Any]]] = {}
    passed: list[str] = []
    for sig in eligible:
        parts = signatures[sig]
        validation[sig] = {}
        all_periods_pass = True
        for source_name in source_names:
            rows = [r for r in parent_rows[source_name] if all(p in r.get("markers", []) for p in parts)]
            m = _signature_metric(rows)
            validation[sig][source_name] = m
            if source_name != discovery_source:
                if m["evaluable_count"] < validation_min_support or m["net_mfe_q25"] is None or m["net_mfe_q25"] <= 0:
                    all_periods_pass = False
        if all_periods_pass:
            passed.append(sig)

    def rank_key(sig: str) -> tuple[float, float, int]:
        vals = [validation[sig][s] for s in source_names]
        q25s = [float(v["net_mfe_q25"]) for v in vals if v["net_mfe_q25"] is not None]
        meds = [float(v["net_mfe_q50"]) for v in vals if v["net_mfe_q50"] is not None]
        support = sum(int(v["evaluable_count"]) for v in vals)
        return (min(q25s) if q25s else -999.0, min(meds) if meds else -999.0, support)

    eligible_ranked = sorted(eligible, key=rank_key, reverse=True)
    passed_ranked = sorted(passed, key=rank_key, reverse=True)

    candidate_table: list[dict[str, Any]] = []
    for sig in eligible_ranked[:100]:
        vals = validation[sig]
        candidate_table.append({
            "signature": sig,
            "parts": list(signatures[sig]),
            "passed_all_validation_periods": sig in passed,
            "by_period": vals,
            "min_period_q25_net_mfe": min(float(vals[s]["net_mfe_q25"]) for s in source_names if vals[s]["net_mfe_q25"] is not None),
            "min_period_median_net_mfe": min(float(vals[s]["net_mfe_q50"]) for s in source_names if vals[s]["net_mfe_q50"] is not None),
            "total_evaluable": sum(int(vals[s]["evaluable_count"]) for s in source_names),
        })

    return {
        "schema": "A1_TELEGRAM_MG_SEQUENCE_DISCOVERY_V4",
        "status": "RESEARCH_CANDIDATE_NOT_CANONICAL",
        "parent_behavior": PARENT,
        "method": "BACKWARD_PUBLICATION_SEQUENCE_SIGNATURE_MINING",
        "source_names": list(source_names),
        "discovery_source": discovery_source,
        "validation_sources": list(source_names[1:]),
        "discovery_min_support": discovery_min_support,
        "validation_min_support": validation_min_support,
        "max_signature_size": max_signature_size,
        "parent_metrics": {s: _metric(parent_rows[s]) for s in source_names},
        "parent_candidate_counts": {s: len(parent_rows[s]) for s in source_names},
        "discovered_signature_count": len(signatures),
        "discovery_q25_positive_signature_count": len(eligible),
        "cross_period_pass_count": len(passed_ranked),
        "cross_period_passed_signatures": passed_ranked[:50],
        "candidate_table": candidate_table,
        "packet_counts": packet_counts,
        "future_data_used_for_signature_state": False,
        "future_data_used_for_research_outcome_only": True,
        "signal_entry_separation": "SIGNAL_AT_PUBLICATION_SLOT__ENTRY_NEXT_ELIGIBLE_BAR_OPEN_PLUS_CAUSAL_OBSERVED_STEP_PROXY",
        "h_plus_1_used": False,
        "march_2025_oos_touched": False,
        "change_policy": "STRUCTURAL_SEQUENCE_PARTITION_OF_FAILED_PARENT;NO_NUMERIC_TRADING_THRESHOLD_RESCUE",
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-telegram-mg-sequence-discovery-v4")
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--software-revision", required=True)
    p.add_argument("--drive-output-folder-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prior-window", type=int, default=2)
    p.add_argument("--buy-fee-pct", type=float, required=True)
    p.add_argument("--sell-fee-pct", type=float, required=True)
    p.add_argument("--discovery-min-support", type=int, default=20)
    p.add_argument("--validation-min-support", type=int, default=15)
    p.add_argument("--max-signature-size", type=int, default=3)
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
        source_names=a.source_name,
        params=params,
        prior_window=a.prior_window,
        buy_fee_pct=a.buy_fee_pct,
        sell_fee_pct=a.sell_fee_pct,
        discovery_min_support=a.discovery_min_support,
        validation_min_support=a.validation_min_support,
        max_signature_size=a.max_signature_size,
    )
    report = {**report, "request_id": a.request_id, "software_revision": a.software_revision}
    Path(a.output).write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, a.drive_output_folder_id)
    safe = "".join(ch for ch in a.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_SEQUENCE_DISCOVERY_V4__{safe}.json", obj=report)
    print(dumps({
        "pass": True,
        "drive_artifact": uploaded,
        "parent_candidate_counts": report["parent_candidate_counts"],
        "discovery_q25_positive_signature_count": report["discovery_q25_positive_signature_count"],
        "cross_period_pass_count": report["cross_period_pass_count"],
        "cross_period_passed_signatures": report["cross_period_passed_signatures"][:10],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
