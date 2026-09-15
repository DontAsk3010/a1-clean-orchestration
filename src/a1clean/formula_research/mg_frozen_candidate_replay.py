from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .handbook_candidates import CandidateParams
from .telegram_mg_outcome_first_discovery_v5 import _metric, _scan_source


REPORT_CAPITAL_PER_PICK_RP = 5_000_000.0


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
            str(row.get("source")),
            str(row.get("trading_date")),
            str(row.get("ticker")),
            str(row.get("signal_timestamp")),
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


def replay_pack(
    pack: Mapping[str, Any], *, source_names: Sequence[str], params: CandidateParams,
    prior_window: int, buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    if pack.get("schema") != "A1_TELEGRAM_MG_FROZEN_CANDIDATE_PACK_V1":
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

    matched, _, packet_counts = _scan_source(
        source_names=source_names,
        params=params,
        prior_window=prior_window,
        buy_fee_pct=buy_fee_pct,
        sell_fee_pct=sell_fee_pct,
        candidate_parts=candidate_parts,
    )
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
        formula_selections.sort(
            key=lambda r: (
                str(r.get("trading_date")),
                str(r.get("signal_timestamp")),
                str(r.get("ticker")),
            )
        )
        formulas[fid] = {
            "required_markers": list(candidate_parts[fid]),
            "by_period": period_metrics,
            "total_evaluable": sum(int(m["evaluable_count"]) for m in period_metrics.values()),
            "selections": formula_selections,
        }

    all_selections.sort(
        key=lambda r: (
            str(r.get("trading_date")),
            str(r.get("signal_timestamp")),
            str(r.get("ticker")),
            str(r.get("formula_id")),
        )
    )
    return {
        "schema": "A1_TELEGRAM_MG_FROZEN_CANDIDATE_REPLAY_V2",
        "status": "RESEARCH_REPLAY_NOT_CANONICAL",
        "source_names": list(source_names),
        "formula_count": len(formulas),
        "formulas": formulas,
        "selections": all_selections,
        "daily_union": _daily_union(all_selections),
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
        effort_lookback=a.effort_lookback,
        progress_lookback=a.progress_lookback,
        high_lookback=a.high_lookback,
        recovery_lookback=a.recovery_lookback,
        low_stabilization_bars=a.low_stabilization_bars,
        early_checkpoint_bar=a.early_checkpoint_bar,
        late_lift_min_bar=a.late_lift_min_bar,
    )
    pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
    report = replay_pack(
        pack,
        source_names=a.source_name,
        params=params,
        prior_window=a.prior_window,
        buy_fee_pct=a.buy_fee_pct,
        sell_fee_pct=a.sell_fee_pct,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "pass": True,
        "formula_count": report["formula_count"],
        "selection_count": len(report["selections"]),
        "trading_day_count": len(report["daily_union"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
