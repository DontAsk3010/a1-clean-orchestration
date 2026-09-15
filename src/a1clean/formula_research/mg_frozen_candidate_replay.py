from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .comparable_context_cache import build_history_context_series
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, evaluate_intraday_candidates
from .telegram_mg_behavior_topology_v2 import _is_true, _num, _pullback_reaccel_features, _topology_states
from .telegram_mg_multiday_context_study import DayRecord
from .telegram_mg_outcome_first_discovery_v5 import _metric, _outcome_at, _scan_source
from .telegram_mg_replay import evaluate_mg_packet
from .telegram_mg_sequence_discovery_v4 import _snapshot, sequence_markers


REPORT_CAPITAL_PER_PICK_RP = 5_000_000.0
FAST_BRIDGE_MARKERS = frozenset({
    "HELD_FLOW", "PRIOR3_RECLAIM", "REGAIN_RENEWED_HIGH", "REGAIN_FRESH",
})


def _selection_row(fid: str, row: Mapping[str, Any]) -> dict[str, Any]:
    net_mfe = row.get("net_mfe_pct")
    return {
        "formula_id": fid,
        "source": row.get("source"),
        "trading_date": row.get("trading_date"),
        "ticker": row.get("ticker"),
        "signal_timestamp": row.get("timestamp"),
        "signal_price": row.get("signal_price"),
        "entry_proxy": row.get("entry_proxy"),
        "step_proxy": row.get("step_proxy"),
        "net_mfe_pct": net_mfe,
        "max_profit_rp_at_5m": (
            REPORT_CAPITAL_PER_PICK_RP * float(net_mfe) / 100.0
            if net_mfe is not None else None
        ),
        "mae_pct": row.get("mae_pct"),
        "eod_net_pct": row.get("eod_net_pct"),
        "evaluable": bool(row.get("evaluable")),
    }


def _daily_union(selections: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    merged: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in selections:
        key = (
            str(row.get("source")), str(row.get("trading_date")),
            str(row.get("ticker")), str(row.get("signal_timestamp")),
        )
        if key not in merged:
            merged[key] = {
                "source": row.get("source"),
                "trading_date": row.get("trading_date"),
                "ticker": row.get("ticker"),
                "signal_timestamp": row.get("signal_timestamp"),
                "signal_price": row.get("signal_price"),
                "entry_proxy": row.get("entry_proxy"),
                "net_mfe_pct": row.get("net_mfe_pct"),
                "max_profit_rp_at_5m": row.get("max_profit_rp_at_5m"),
                "mae_pct": row.get("mae_pct"),
                "eod_net_pct": row.get("eod_net_pct"),
                "formula_ids": [],
            }
        merged[key]["formula_ids"].append(str(row.get("formula_id")))
    for item in merged.values():
        item["formula_ids"] = sorted(set(item["formula_ids"]))
        grouped[str(item["trading_date"])].append(item)
    for day in grouped:
        grouped[day].sort(key=lambda r: (str(r.get("signal_timestamp")), str(r.get("ticker"))))
    return dict(sorted(grouped.items()))


def _fast_snapshot(*, mg: Mapping[str, Any], base: Mapping[str, Any], pr: Mapping[str, Any]) -> dict[str, bool]:
    c = mg["components"]
    b = base["states"]
    return {
        "FLOW": _is_true(c.get("CONSTRUCTIVE_FLOW")),
        "FRESH": _is_true(c.get("FRESH_HIGH")),
        "VALUE": _is_true(c.get("VALUE_EXPANSION")),
        "RETAINED": _is_true(c.get("EARLY_STRENGTH_RETAINED")),
        "RECOVERY": _is_true(b.get("F05A_SESSION_OPEN_RECOVERY")),
        "PULLBACK": bool(pr.get("had_pullback")),
        "RECLAIM": bool(pr.get("reclaim")),
        "RENEWED_HIGH": bool(pr.get("renewed_high")),
        "WAKE_ACTIVITY": False,
        "WAKE_RANGE": False,
        "WAKE_PATH": False,
    }


def _can_fast_path(candidate_parts: Mapping[str, tuple[str, ...]], parent_gate: Mapping[str, Any] | None) -> bool:
    if parent_gate:
        return False
    used = {m for parts in candidate_parts.values() for m in parts}
    return bool(used) and used.issubset(FAST_BRIDGE_MARKERS)


def _scan_fast_bridge(
    *, source_names: Sequence[str], candidate_parts: Mapping[str, tuple[str, ...]],
    params: CandidateParams, buy_fee_pct: float, sell_fee_pct: float,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    matched: dict[str, list[dict[str, Any]]] = {fid: [] for fid in candidate_parts}
    packet_counts: dict[str, int] = {}
    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        pc = 0
        for _manifest_row, packet in reader.iter_packets():
            pc += 1
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [b for b in all_bars if b.get("session_eligible")]
            if not bars:
                continue
            mg_rows = evaluate_mg_packet(bars, params)
            base_rows = evaluate_intraday_candidates(bars, params)
            publication_snapshots: list[dict[str, bool]] = []
            seen_formula: set[str] = set()
            date = str(packet.identity.trading_date)
            ticker = str(packet.identity.ticker)
            for i, (mg, base) in enumerate(zip(mg_rows, base_rows, strict=True)):
                if not mg.get("publication_slot"):
                    continue
                pr = _pullback_reaccel_features(bars, i, params)
                snap = _fast_snapshot(mg=mg, base=base, pr=pr)
                markers = set(sequence_markers(snap, publication_snapshots))
                for fid, required in candidate_parts.items():
                    if fid in seen_formula:
                        continue
                    if all(marker in markers for marker in required):
                        seen_formula.add(fid)
                        outcome = _outcome_at(bars, i, buy_fee_pct, sell_fee_pct)
                        matched[fid].append({
                            **outcome, "source": source_name, "trading_date": date,
                            "ticker": ticker, "timestamp": mg.get("timestamp"),
                            "signal_price": _num(bars[i].get("close")),
                        })
                publication_snapshots.append(snap)
        packet_counts[source_name] = pc
    return matched, packet_counts


def _previous_close(
    history: Mapping[str, Mapping[str, DayRecord]],
    ticker: str,
    completed_dates: Sequence[str],
) -> float | None:
    ticker_history = history.get(ticker, {})
    for day in reversed(completed_dates):
        record = ticker_history.get(day)
        if record is None:
            continue
        for bar in reversed(record.bars):
            close = _num(bar.get("close"))
            if close is not None and close > 0:
                return float(close)
    return None


def _scan_first_parent_bridge(
    *, source_names: Sequence[str], candidate_parts: Mapping[str, tuple[str, ...]],
    params: CandidateParams, prior_window: int, buy_fee_pct: float, sell_fee_pct: float,
    parent_gate: Mapping[str, Any],
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, int],
    dict[str, list[dict[str, Any]]],
]:
    required_states = tuple(str(x) for x in parent_gate.get("required_current_states") or ())
    if required_states != (
        "J05_FLOW_RESILIENT_CONTINUATION", "J06_EARLY_STRENGTH_RETAINED"
    ):
        raise ValueError("UNSUPPORTED_PARENT_GATE")
    if parent_gate.get("evaluate_signature_only_at_first_parent_match_per_ticker_day") is not True:
        raise ValueError("FIRST_PARENT_MATCH_REQUIRED")

    matched: dict[str, list[dict[str, Any]]] = {fid: [] for fid in candidate_parts}
    packet_counts: dict[str, int] = {}
    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_dates: list[str] = []
    seen_dates: set[str] = set()
    current_date: str | None = None

    slot_times: dict[str, set[str]] = defaultdict(set)
    slot_rows: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(dict)
    )

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
            pc += 1
            date = str(packet.identity.trading_date)
            if current_date is None:
                current_date = date
            elif date != current_date:
                close_date(current_date)
                current_date = date
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [b for b in all_bars if b.get("session_eligible")]
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

            prev_close = _previous_close(history, ticker, completed_dates)
            mg_rows = evaluate_mg_packet(bars, params)
            base_rows = evaluate_intraday_candidates(bars, params)
            publication_snapshots: list[dict[str, bool]] = []
            parent_seen = False
            triggered_formulas: set[str] = set()

            for i, (mg, base) in enumerate(zip(mg_rows, base_rows, strict=True)):
                states, evidence = _topology_states(
                    bars=bars, index=i, mg=mg, base=base,
                    context=context_series[i], params=params,
                )
                if not mg.get("publication_slot"):
                    continue
                timestamp = str(mg.get("timestamp") or "")
                slot_times[date].add(timestamp)
                snap = _snapshot(mg=mg, base=base, evidence=evidence)
                parent_match = all(bool(states.get(s)) for s in required_states)

                if parent_match and not parent_seen:
                    parent_seen = True
                    markers = set(sequence_markers(snap, publication_snapshots))
                    for fid, required in candidate_parts.items():
                        if all(marker in markers for marker in required):
                            triggered_formulas.add(fid)
                            outcome = _outcome_at(bars, i, buy_fee_pct, sell_fee_pct)
                            matched[fid].append({
                                **outcome, "source": source_name, "trading_date": date,
                                "ticker": ticker, "timestamp": mg.get("timestamp"),
                                "signal_price": _num(bars[i].get("close")),
                            })

                if triggered_formulas and parent_match:
                    price = _num(bars[i].get("close"))
                    chg_pct = None
                    if price is not None and prev_close is not None and prev_close > 0:
                        chg_pct = (float(price) / float(prev_close) - 1.0) * 100.0
                    targets = mg.get("targets") or {}
                    row = {
                        "ticker": ticker,
                        "price": price,
                        "chg_pct": chg_pct,
                        "tp1": _num(targets.get("tp1")),
                        "tp2": _num(targets.get("tp2")),
                        "formula_ids": sorted(triggered_formulas),
                    }
                    existing = slot_rows[date][timestamp].get(ticker)
                    if existing is None:
                        slot_rows[date][timestamp][ticker] = row
                    else:
                        existing["formula_ids"] = sorted(
                            set(existing["formula_ids"]) | triggered_formulas
                        )

                publication_snapshots.append(snap)

            history.setdefault(ticker, {})[date] = DayRecord(
                trading_date=date, bars=tuple(dict(b) for b in bars)
            )
        packet_counts[source_name] = pc
    close_date(current_date)

    telegram_days: dict[str, list[dict[str, Any]]] = {}
    for date in sorted(slot_times):
        snapshots: list[dict[str, Any]] = []
        for timestamp in sorted(slot_times[date]):
            rows = list(slot_rows[date].get(timestamp, {}).values())
            rows.sort(key=lambda row: str(row.get("ticker")))
            snapshots.append({
                "timestamp": timestamp,
                "time": timestamp[11:16] if len(timestamp) >= 16 else timestamp,
                "rows": rows,
                "empty": len(rows) == 0,
            })
        telegram_days[date] = snapshots

    return matched, packet_counts, telegram_days


def replay_pack(
    pack: Mapping[str, Any], *, source_names: Sequence[str], params: CandidateParams,
    prior_window: int, buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    if pack.get("schema") not in {
        "A1_TELEGRAM_MG_FROZEN_CANDIDATE_PACK_V1",
        "A1_TELEGRAM_MG_FROZEN_CANDIDATE_PACK_V2",
    }:
        raise ValueError("UNSUPPORTED_FROZEN_PACK_SCHEMA")
    if pack.get("future_data_in_executable_formula") is not False:
        raise ValueError("FROZEN_PACK_FUTURE_LEAKAGE")

    candidate_parts: dict[str, tuple[str, ...]] = {}
    for row in pack.get("formulas", []):
        spec = row.get("spec") or {}
        formula_id = str(spec.get("formula_id") or "")
        required = tuple(str(x) for x in spec.get("required") or [])
        forbidden = tuple(str(x) for x in spec.get("forbidden") or [])
        if not formula_id or not required:
            raise ValueError("INVALID_FROZEN_FORMULA")
        if forbidden:
            raise ValueError("FORBIDDEN_MARKER_REPLAY_NOT_IMPLEMENTED")
        candidate_parts[formula_id] = required

    telegram_days: dict[str, list[dict[str, Any]]] = {}
    parent_gate = pack.get("parent_gate") if isinstance(pack.get("parent_gate"), Mapping) else None
    if parent_gate:
        matched, packet_counts, telegram_days = _scan_first_parent_bridge(
            source_names=source_names, candidate_parts=candidate_parts, params=params,
            prior_window=prior_window, buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            parent_gate=parent_gate,
        )
        implementation = "FIRST_K06_PARENT_GATE_EXACT_V4_WITH_5MIN_TELEGRAM_SNAPSHOTS"
    elif _can_fast_path(candidate_parts, parent_gate):
        matched, packet_counts = _scan_fast_bridge(
            source_names=source_names, candidate_parts=candidate_parts, params=params,
            buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
        )
        implementation = "TARGETED_FAST_BRIDGE"
    else:
        matched, _, packet_counts = _scan_source(
            source_names=source_names, params=params, prior_window=prior_window,
            buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            candidate_parts=candidate_parts,
        )
        implementation = "GENERIC_V5_SCANNER"

    by_formula_period: dict[str, dict[str, list[dict[str, Any]]]] = {
        fid: {s: [] for s in source_names} for fid in candidate_parts
    }
    all_selections: list[dict[str, Any]] = []
    for fid, rows in matched.items():
        for row in rows:
            by_formula_period[fid][str(row["source"])].append(row)
            all_selections.append(_selection_row(fid, row))

    formulas: dict[str, Any] = {}
    for fid in candidate_parts:
        period_metrics = {s: _metric(by_formula_period[fid][s]) for s in source_names}
        formula_selections = [r for r in all_selections if r["formula_id"] == fid]
        formula_selections.sort(key=lambda r: (
            str(r.get("trading_date")), str(r.get("signal_timestamp")), str(r.get("ticker"))
        ))
        formulas[fid] = {
            "required_markers": list(candidate_parts[fid]),
            "by_period": period_metrics,
            "total_evaluable": sum(int(m["evaluable_count"]) for m in period_metrics.values()),
            "selections": formula_selections,
        }

    all_selections.sort(key=lambda r: (
        str(r.get("trading_date")), str(r.get("signal_timestamp")),
        str(r.get("ticker")), str(r.get("formula_id"))
    ))
    return {
        "schema": "A1_TELEGRAM_MG_FROZEN_CANDIDATE_REPLAY_V5",
        "status": "RESEARCH_REPLAY_NOT_CANONICAL",
        "implementation": implementation,
        "parent_gate": parent_gate,
        "source_names": list(source_names),
        "formula_count": len(formulas),
        "formulas": formulas,
        "selections": all_selections,
        "daily_union": _daily_union(all_selections),
        "telegram_5min_days": telegram_days,
        "telegram_publication_policy": "09:00_AND_EVERY_OBSERVED_5MIN_PUBLICATION_SLOT",
        "telegram_empty_slot_policy": "EMIT_SEPARATOR",
        "telegram_display_persistence_policy": (
            "AFTER_FIRST_VALID_V4_TRIGGER_TODAY__DISPLAY_WHILE_CURRENT_K06_VALID__"
            "REAPPEAR_IF_CURRENT_K06_VALID_AGAIN"
        ),
        "telegram_columns": ["CODE", "PRICE", "CHG%", "TP-1", "TP-2"],
        "report_capital_per_pick_rp": REPORT_CAPITAL_PER_PICK_RP,
        "profit_field_semantics": "MAX_NET_FAVORABLE_EXCURSION_AFTER_BUY_SELL_FEES_AND_STEP_PROXY__NOT_REALIZED_EXIT_PNL",
        "packet_counts": packet_counts,
        "first_causal_match_per_ticker_day": True,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_measurement_only": True,
        "h_plus_1_used": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-mg-frozen-candidate-replay")
    p.add_argument("--pack", required=True)
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prior-window", type=int, default=2)
    p.add_argument("--buy-fee-pct", type=float, required=True)
    p.add_argument("--sell-fee-pct", type=float, required=True)
    p.add_argument("--effort-lookback", type=int, required=True)
    p.add_argument("--progress-lookback", type=int, required=True)
    p.add_argument("--high-lookback", type=int, required=True)
    p.add_argument("--recovery-lookback", type=int, required=True)
    p.add_argument("--low-stabilization-bars", type=int, required=True)
    p.add_argument("--early-checkpoint-bar", type=int, required=True)
    p.add_argument("--late-lift-min-bar", type=int, required=True)
    a = p.parse_args(argv)
    params = CandidateParams(
        effort_lookback=a.effort_lookback, progress_lookback=a.progress_lookback,
        high_lookback=a.high_lookback, recovery_lookback=a.recovery_lookback,
        low_stabilization_bars=a.low_stabilization_bars,
        early_checkpoint_bar=a.early_checkpoint_bar,
        late_lift_min_bar=a.late_lift_min_bar,
    )
    pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
    report = replay_pack(
        pack, source_names=a.source_name, params=params, prior_window=a.prior_window,
        buy_fee_pct=a.buy_fee_pct, sell_fee_pct=a.sell_fee_pct,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "pass": True, "formula_count": report["formula_count"],
        "selection_count": len(report["selections"]),
        "trading_day_count": len(report["daily_union"]),
        "telegram_day_count": len(report.get("telegram_5min_days") or {}),
        "telegram_snapshot_count": sum(
            len(v) for v in (report.get("telegram_5min_days") or {}).values()
        ),
        "implementation": report["implementation"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
