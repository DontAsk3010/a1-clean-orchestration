from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .handbook_candidates import CandidateParams
from .telegram_mg_outcome_first_discovery_v5 import _metric, _q
from .telegram_mg_trajectory_contrast_v6 import (
    _iter_source_ticker_days,
    _mine_family,
    _signature_match,
)


def _discovery_thresholds(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [r for r in events if r.get("evaluable") and r.get("net_mfe_pct") is not None]
    positive = [r for r in rows if float(r["net_mfe_pct"]) > 0]
    if not positive:
        raise ValueError("V7_NO_POSITIVE_DISCOVERY_EVENTS")
    mfe = [float(r["net_mfe_pct"]) for r in positive]
    q75 = _q(mfe, 0.75)
    q85 = _q(mfe, 0.85)
    top = [r for r in positive if q75 is not None and float(r["net_mfe_pct"]) >= float(q75)]
    first = [int(r["first_positive_net_offset_bars"]) for r in top if r.get("first_positive_net_offset_bars") is not None]
    mae = [float(r["pre_peak_mae_pct"]) for r in top if r.get("pre_peak_mae_pct") is not None]
    rr = [float(r["reward_to_pre_peak_adverse"]) for r in top if r.get("reward_to_pre_peak_adverse") is not None]
    return {
        "positive_mfe_q75": q75,
        "positive_mfe_q85": q85,
        "top_winner_fast_q25_bars": int(round(_q(first, 0.25))) if first else None,
        "top_winner_pre_peak_mae_q50": _q(mae, 0.50) if mae else None,
        "top_winner_reward_to_adverse_q50": _q(rr, 0.50) if rr else None,
    }


def _family_hit(row: Mapping[str, Any], family: str, t: Mapping[str, Any]) -> bool:
    if not row.get("evaluable") or row.get("net_mfe_pct") is None:
        return False
    mfe = float(row["net_mfe_pct"])
    q75 = t.get("positive_mfe_q75")
    q85 = t.get("positive_mfe_q85")
    fast = t.get("top_winner_fast_q25_bars")
    clean = t.get("top_winner_pre_peak_mae_q50")
    rr50 = t.get("top_winner_reward_to_adverse_q50")
    first = row.get("first_positive_net_offset_bars")
    mae = row.get("pre_peak_mae_pct")
    rr = row.get("reward_to_pre_peak_adverse")
    if family == "HAKA_FAST_CLEAN":
        return (
            q75 is not None and mfe >= float(q75)
            and first is not None and fast is not None and int(first) <= int(fast)
            and mae is not None and clean is not None and float(mae) >= float(clean)
            and (rr50 is None or rr is None or float(rr) >= float(rr50))
        )
    if family == "HAKA_STRONG_CLEAN":
        return (
            q85 is not None and mfe >= float(q85)
            and mae is not None and clean is not None and float(mae) >= float(clean)
        )
    if family == "HAKA_EFFICIENT":
        return (
            q75 is not None and mfe >= float(q75)
            and mae is not None and clean is not None and float(mae) >= float(clean)
            and rr is not None and rr50 is not None and float(rr) >= float(rr50)
        )
    raise ValueError(f"V7_UNKNOWN_FAMILY:{family}")


def _choose_positive(events: Sequence[Mapping[str, Any]], family: str, t: Mapping[str, Any]):
    for event in events:
        if _family_hit(event, family, t):
            return event
    return None


def _choose_negative(events: Sequence[Mapping[str, Any]], t: Mapping[str, Any]):
    evals = [e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    if not evals:
        return None
    losers = [e for e in evals if float(e["net_mfe_pct"]) <= 0]
    if losers:
        return max(losers, key=lambda e: float(e["net_mfe_pct"]))
    q75 = t.get("positive_mfe_q75")
    weak = [e for e in evals if q75 is not None and float(e["net_mfe_pct"]) < float(q75)]
    if weak:
        return max(weak, key=lambda e: float(e["net_mfe_pct"]))
    return min(evals, key=lambda e: float(e["net_mfe_pct"]))


def _scan_validation(*, source_name: str, params: CandidateParams, prior_window: int,
                     buy_fee_pct: float, sell_fee_pct: float,
                     thresholds: Mapping[str, Any], candidates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    matched: dict[str, list[dict[str, Any]]] = {cid: [] for cid in candidates}
    ticker_days = 0
    for date, ticker, events in _iter_source_ticker_days(
        source_name=source_name, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    ):
        ticker_days += 1
        for cid, spec in candidates.items():
            for e in events:
                if _signature_match(set(e.get("markers", ())), spec["required"], spec["forbidden"]):
                    matched[cid].append({**e, "trading_date": date, "ticker": ticker})
                    break
    out = {}
    for cid, rows in matched.items():
        fam = candidates[cid]["family"]
        hits = sum(_family_hit(r, fam, thresholds) for r in rows)
        out[cid] = {
            "metric": _metric(rows),
            "high_conviction_hit_count": hits,
            "high_conviction_hit_rate": hits / len(rows) if rows else None,
            "rows_count": len(rows),
        }
    return {"ticker_day_count": ticker_days, "candidate_results": out}


def build_report(*, source_names: Sequence[str], params: CandidateParams, prior_window: int,
                 buy_fee_pct: float, sell_fee_pct: float, min_support: int,
                 validation_min_support: int, max_required: int, max_forbidden: int,
                 top_positive_markers: int, top_negative_markers: int, top_signatures: int) -> dict[str, Any]:
    if len(source_names) < 3:
        raise ValueError("V7_REQUIRES_DISCOVERY_PLUS_TWO_VALIDATION_PERIODS")
    discovery = source_names[0]
    validation_sources = list(source_names[1:])
    all_events: list[dict[str, Any]] = []
    discovery_days: list[tuple[str, str, list[dict[str, Any]]]] = []
    for date, ticker, events in _iter_source_ticker_days(
        source_name=discovery, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    ):
        discovery_days.append((date, ticker, events))
        all_events.extend(events)
    thresholds = _discovery_thresholds(all_events)
    families = ("HAKA_FAST_CLEAN", "HAKA_STRONG_CLEAN", "HAKA_EFFICIENT")
    discovery_by_family = {}
    candidates: dict[str, dict[str, Any]] = {}
    for family in families:
        positives = []
        negatives = []
        for date, ticker, events in discovery_days:
            p = _choose_positive(events, family, thresholds)
            if p is not None:
                positives.append({**p, "trading_date": date, "ticker": ticker})
            n = _choose_negative(events, thresholds)
            if n is not None:
                negatives.append({**n, "trading_date": date, "ticker": ticker})
        mined = _mine_family(
            positives, negatives, min_support=min_support,
            max_required=max_required, max_forbidden=max_forbidden,
            top_positive_markers=top_positive_markers,
            top_negative_markers=top_negative_markers,
            top_signatures=top_signatures,
        )
        discovery_by_family[family] = mined
        for i, spec in enumerate(mined["candidates"], start=1):
            cid = f"MG_V7_{family}_{i:03d}"
            candidates[cid] = {"family": family, **spec}
    validation = {
        src: _scan_validation(
            source_name=src, params=params, prior_window=prior_window,
            buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            thresholds=thresholds, candidates=candidates,
        ) for src in validation_sources
    }
    table = []
    strict_ids = []
    for cid, spec in candidates.items():
        vals = [validation[s]["candidate_results"][cid] for s in validation_sources]
        support_ok = all(int(v["rows_count"]) >= validation_min_support for v in vals)
        q25s = [v["metric"].get("net_mfe_q25") for v in vals]
        meds = [v["metric"].get("net_mfe_q50") for v in vals]
        strict = support_ok and all(x is not None and float(x) > 0 for x in q25s) and all(x is not None and float(x) > 0 for x in meds)
        if strict:
            strict_ids.append(cid)
        table.append({
            "candidate_id": cid,
            "family": spec["family"],
            "required": spec["required"],
            "forbidden": spec["forbidden"],
            "discovery_precision": spec["discovery_precision"],
            "discovery_recall": spec["discovery_recall"],
            "strict_cross_period_pass": strict,
            "min_validation_q25_net_mfe": min(float(x) for x in q25s if x is not None) if any(x is not None for x in q25s) else None,
            "min_validation_median_net_mfe": min(float(x) for x in meds if x is not None) if any(x is not None for x in meds) else None,
            "validation": {s: validation[s]["candidate_results"][cid] for s in validation_sources},
        })
    table.sort(key=lambda r: (
        bool(r["strict_cross_period_pass"]),
        float(r["min_validation_q25_net_mfe"] if r["min_validation_q25_net_mfe"] is not None else -999),
        float(r["min_validation_median_net_mfe"] if r["min_validation_median_net_mfe"] is not None else -999),
        float(r["discovery_precision"]),
    ), reverse=True)
    return {
        "schema": "A1_TELEGRAM_MG_HIGH_CONVICTION_V7_RESULT_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "method": "FULL_UNIVERSE_5MIN_HIGH_CONVICTION_OUTCOME_FIRST_WITH_FAILURE_CONTRAST",
        "source_names": list(source_names),
        "discovery_source": discovery,
        "validation_sources": validation_sources,
        "discovery_ticker_day_count": len(discovery_days),
        "discovery_event_count": len(all_events),
        "thresholds_frozen_from_discovery": thresholds,
        "discovery_by_family": discovery_by_family,
        "candidate_count": len(candidates),
        "strict_cross_period_pass_count": len(strict_ids),
        "strict_cross_period_passed_candidate_ids": strict_ids,
        "candidate_table": table,
        "validation": validation,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_discovery_label_only": True,
        "march_2025_oos_touched": False,
        "h_plus_1_used": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prior-window", type=int, default=3)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=30)
    p.add_argument("--validation-min-support", type=int, default=30)
    p.add_argument("--max-required", type=int, default=3)
    p.add_argument("--max-forbidden", type=int, default=1)
    p.add_argument("--top-positive-markers", type=int, default=18)
    p.add_argument("--top-negative-markers", type=int, default=10)
    p.add_argument("--top-signatures", type=int, default=60)
    p.add_argument("--effort-lookback", type=int, default=5)
    p.add_argument("--progress-lookback", type=int, default=5)
    p.add_argument("--high-lookback", type=int, default=5)
    p.add_argument("--recovery-lookback", type=int, default=5)
    p.add_argument("--low-stabilization-bars", type=int, default=3)
    p.add_argument("--early-checkpoint-bar", type=int, default=30)
    p.add_argument("--late-lift-min-bar", type=int, default=120)
    a = p.parse_args()
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
        min_support=a.min_support, validation_min_support=a.validation_min_support,
        max_required=a.max_required, max_forbidden=a.max_forbidden,
        top_positive_markers=a.top_positive_markers, top_negative_markers=a.top_negative_markers,
        top_signatures=a.top_signatures,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
