from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .handbook_candidates import CandidateParams
from .telegram_mg_outcome_first_discovery_v5 import _metric, _scan_source


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
            # V5 scanner currently indexes positive marker membership. Forbidden
            # states require an explicit scanner extension before replay rather
            # than silently ignoring them.
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
    for fid, rows in matched.items():
        for row in rows:
            by_formula_period[fid][str(row["source"])].append(row)

    formulas: dict[str, Any] = {}
    for fid in candidate_parts:
        period_metrics = {s: _metric(by_formula_period[fid][s]) for s in source_names}
        formulas[fid] = {
            "required_markers": list(candidate_parts[fid]),
            "by_period": period_metrics,
            "total_evaluable": sum(int(m["evaluable_count"]) for m in period_metrics.values()),
        }

    return {
        "schema": "A1_TELEGRAM_MG_FROZEN_CANDIDATE_REPLAY_V1",
        "status": "RESEARCH_REPLAY_NOT_CANONICAL",
        "source_names": list(source_names),
        "formula_count": len(formulas),
        "formulas": formulas,
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
    print(json.dumps({"pass": True, "formula_count": report["formula_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
