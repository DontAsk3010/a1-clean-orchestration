from __future__ import annotations

import argparse
from collections import defaultdict
from json import dumps
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .comparable_context_cache import build_history_context_series
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, evaluate_intraday_candidates
from .telegram_mg_behavior_topology_v2 import _evaluate_trade, _num, _topology_states
from .telegram_mg_multiday_context_study import DayRecord
from .telegram_mg_replay import evaluate_mg_packet
from .telegram_mg_structural_discovery_v3 import FORMULAS, _derived, _metric


def build_report(*, source_names: Sequence[str], params: CandidateParams, prior_window: int,
                 buy_fee_pct: float, sell_fee_pct: float) -> dict[str, Any]:
    params.validate()
    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_dates: list[str] = []
    seen_dates: set[str] = set()
    current_date: str | None = None
    by_source: dict[str, dict[str, list[dict[str, Any]]]] = {
        s: {f: [] for f in FORMULAS} for s in source_names
    }
    by_day: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {
        s: defaultdict(lambda: {f: [] for f in FORMULAS}) for s in source_names
    }
    samples: dict[str, list[dict[str, Any]]] = {f: [] for f in FORMULAS}
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
            ticker_history = history.get(ticker, {})
            if len(prior_dates) == prior_window:
                context_series = build_history_context_series(
                    bars=bars,
                    history_by_date=ticker_history,
                    prior_dates=prior_dates,
                )
            else:
                context_series = [None] * len(bars)

            mg_rows = evaluate_mg_packet(bars, params)
            base_rows = evaluate_intraday_candidates(bars, params)
            state_rows: list[dict[str, bool]] = []
            first_seen: set[str] = set()

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

                recent = state_rows[max(0, i - 5):i]
                formulas = _derived(states, recent)
                for formula_id, matched in formulas.items():
                    if not matched or formula_id in first_seen:
                        continue
                    first_seen.add(formula_id)
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
                    row = {
                        **outcome,
                        "source": source_name,
                        "trading_date": date,
                        "ticker": ticker,
                        "timestamp": mg.get("timestamp"),
                        "signal_price": _num(bars[i].get("close")),
                        "base_paths": [k for k, v in states.items() if v],
                        "context": evidence.get("context"),
                    }
                    by_source[source_name][formula_id].append(row)
                    by_day[source_name][date][formula_id].append(row)
                    if len(samples[formula_id]) < 40:
                        samples[formula_id].append(row)

            history.setdefault(ticker, {})[date] = DayRecord(
                trading_date=date, bars=tuple(dict(b) for b in bars)
            )
        packet_counts[source_name] = pc
    close_date(current_date)

    aggregate = {s: {f: _metric(rows) for f, rows in d.items()} for s, d in by_source.items()}
    daily = {
        s: {d: {f: _metric(rows) for f, rows in formulas.items()} for d, formulas in sorted(days.items())}
        for s, days in by_day.items()
    }
    stability: dict[str, Any] = {}
    for f in FORMULAS:
        rows = [aggregate[s][f] for s in source_names if aggregate[s][f]["evaluable_count"] > 0]
        q25s = [x["net_mfe_q25"] for x in rows if x["net_mfe_q25"] is not None]
        meds = [x["net_mfe_q50"] for x in rows if x["net_mfe_q50"] is not None]
        pos = [x["positive_net_mfe_rate"] for x in rows if x["positive_net_mfe_rate"] is not None]
        stability[f] = {
            "period_count": len(rows),
            "total_candidates": sum(aggregate[s][f]["candidate_count"] for s in source_names),
            "min_period_q25_net_mfe": min(q25s) if q25s else None,
            "median_period_q25_net_mfe": median(q25s) if q25s else None,
            "min_period_median_net_mfe": min(meds) if meds else None,
            "median_period_median_net_mfe": median(meds) if meds else None,
            "min_period_positive_net_mfe_rate": min(pos) if pos else None,
            "median_period_positive_net_mfe_rate": median(pos) if pos else None,
        }

    ranking = sorted(
        FORMULAS,
        key=lambda f: (
            stability[f]["min_period_q25_net_mfe"] if stability[f]["min_period_q25_net_mfe"] is not None else -999,
            stability[f]["min_period_median_net_mfe"] if stability[f]["min_period_median_net_mfe"] is not None else -999,
            stability[f]["min_period_positive_net_mfe_rate"] if stability[f]["min_period_positive_net_mfe_rate"] is not None else -1,
            stability[f]["total_candidates"],
        ),
        reverse=True,
    )
    return {
        "schema": "A1_TELEGRAM_MG_STRUCTURAL_DISCOVERY_V3",
        "status": "RESEARCH_CANDIDATE_NOT_CANONICAL",
        "implementation": "CACHED_COMPARABLE_CONTEXT_EXACT_PARITY",
        "purpose": "REPLACE_STRUCTURALLY_WEAK_MG_TOPOLOGIES_WITH_TRANSITION_AND_CONSENSUS_FORMULAS_AND_MEASURE_RAW_POST_SIGNAL_EXECUTABLE_OUTCOME_DISTRIBUTIONS",
        "source_names": list(source_names),
        "formulas": list(FORMULAS),
        "aggregate": aggregate,
        "daily": daily,
        "cross_period_stability": stability,
        "research_ranking": ranking,
        "samples": samples,
        "packet_counts": packet_counts,
        "first_causal_appearance_only_per_ticker_day_formula": True,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_research_outcome_only": True,
        "signal_entry_separation": "SIGNAL_AT_PUBLICATION_SLOT__ENTRY_NEXT_ELIGIBLE_BAR_OPEN_PLUS_CAUSAL_OBSERVED_STEP_PROXY",
        "h_plus_1_used": False,
        "march_2025_oos_touched": False,
        "change_policy": "STRUCTURAL_FAILURE_REQUIRES_COMPONENT_TOPOLOGY_REPLACEMENT_NOT_THRESHOLD_RESCUE_ONLY",
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-telegram-mg-structural-discovery-v3-fast")
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--software-revision", required=True)
    p.add_argument("--drive-output-folder-id", required=True)
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
    )
    report = {**report, "request_id": a.request_id, "software_revision": a.software_revision}
    Path(a.output).write_text(dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, a.drive_output_folder_id)
    safe = "".join(ch for ch in a.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_STRUCTURAL_DISCOVERY_V3__{safe}.json", obj=report)
    print(dumps({"pass": True, "drive_artifact": uploaded, "ranking": report["research_ranking"], "stability": report["cross_period_stability"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
