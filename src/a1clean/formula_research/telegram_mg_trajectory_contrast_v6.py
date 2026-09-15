from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import combinations
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .comparable_context_cache import build_history_context_series
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams
from .outcome_path_quality import evaluate_outcome_path_quality
from .telegram_mg_multiday_context_study import DayRecord
from .telegram_mg_outcome_first_discovery_v5 import _iter_packet_events, _metric, _q


def _label_thresholds(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | int | None]:
    pos = [r for r in rows if r.get("evaluable") and r.get("net_mfe_pct") is not None and float(r["net_mfe_pct"]) > 0]
    if not pos:
        raise ValueError("NO_POSITIVE_DISCOVERY_EVENTS")
    mfe = [float(r["net_mfe_pct"]) for r in pos]
    mae = [float(r["pre_peak_mae_pct"]) for r in pos if r.get("pre_peak_mae_pct") is not None]
    first = [int(r["first_positive_net_offset_bars"]) for r in pos if r.get("first_positive_net_offset_bars") is not None]
    ratio = [float(r["reward_to_pre_peak_adverse"]) for r in pos if r.get("reward_to_pre_peak_adverse") is not None]
    retained = [
        float(r["eod_net_pct"]) / float(r["net_mfe_pct"])
        for r in pos
        if r.get("eod_net_pct") is not None and float(r["eod_net_pct"]) > 0 and float(r["net_mfe_pct"]) > 0
    ]
    return {
        "positive_mfe_q50": _q(mfe, 0.50),
        "positive_mfe_q75": _q(mfe, 0.75),
        "clean_pre_peak_mae_q50": _q(mae, 0.50) if mae else None,
        "fast_first_positive_q50_bars": int(round(_q(first, 0.50))) if first else None,
        "reward_to_adverse_q50": _q(ratio, 0.50) if ratio else None,
        "retained_fraction_q50": _q(retained, 0.50) if retained else None,
    }


def _classifies(row: Mapping[str, Any], family: str, t: Mapping[str, Any]) -> bool:
    if not row.get("evaluable") or row.get("net_mfe_pct") is None:
        return False
    mfe = float(row["net_mfe_pct"])
    if family == "ANY_POSITIVE":
        return mfe > 0
    if mfe <= 0:
        return False
    q50 = t.get("positive_mfe_q50")
    q75 = t.get("positive_mfe_q75")
    clean = t.get("clean_pre_peak_mae_q50")
    fast = t.get("fast_first_positive_q50_bars")
    rr = t.get("reward_to_adverse_q50")
    retained = t.get("retained_fraction_q50")
    if family == "FAST_CLEAN":
        first = row.get("first_positive_net_offset_bars")
        mae = row.get("pre_peak_mae_pct")
        reward = row.get("reward_to_pre_peak_adverse")
        return (
            q50 is not None and mfe >= float(q50)
            and first is not None and fast is not None and int(first) <= int(fast)
            and mae is not None and clean is not None and float(mae) >= float(clean)
            and (reward is None or rr is None or float(reward) >= float(rr))
        )
    if family == "STRONG_RUNNER":
        mae = row.get("pre_peak_mae_pct")
        return (
            q75 is not None and mfe >= float(q75)
            and (mae is None or clean is None or float(mae) >= float(clean))
        )
    if family == "RETAINED_WINNER":
        eod = row.get("eod_net_pct")
        frac = (float(eod) / mfe) if eod is not None and mfe > 0 else None
        return (
            q50 is not None and mfe >= float(q50)
            and eod is not None and float(eod) > 0
            and frac is not None and retained is not None and frac >= float(retained)
        )
    raise ValueError(f"UNKNOWN_FAMILY:{family}")


def _enrich_event(
    event: Mapping[str, Any], bars: Sequence[Mapping[str, Any]],
    buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    row = dict(event)
    if not row.get("evaluable"):
        return row
    entry = row.get("entry_proxy")
    step = row.get("step_proxy")
    index = row.get("signal_index")
    if entry is None or step is None or index is None:
        return row
    q = evaluate_outcome_path_quality(
        bars=bars, signal_index=int(index), entry_proxy=float(entry), step_proxy=float(step),
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    )
    row.update(q)
    return row


def _iter_source_ticker_days(
    *, source_name: str, params: CandidateParams, prior_window: int,
    buy_fee_pct: float, sell_fee_pct: float,
):
    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_dates: list[str] = []
    seen_dates: set[str] = set()
    current_date: str | None = None

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

    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    packet_count = 0
    for _manifest_row, packet in reader.iter_packets():
        date = str(packet.identity.trading_date)
        if current_date is None:
            current_date = date
        elif date != current_date:
            close_date(current_date)
            current_date = date

        all_bars, _ = packet_to_formula_bars(packet)
        bars = [b for b in all_bars if b.get("session_eligible")]
        packet_count += 1
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
        events = [
            _enrich_event(e, bars, buy_fee_pct, sell_fee_pct)
            for e in _iter_packet_events(
                bars=bars, context_series=context_series, params=params,
                buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            )
        ]
        yield date, ticker, events
        history.setdefault(ticker, {})[date] = DayRecord(
            trading_date=date, bars=tuple(dict(b) for b in bars)
        )
    close_date(current_date)
    return packet_count


def _first_family_rep(events: Sequence[Mapping[str, Any]], family: str, t: Mapping[str, Any]):
    for e in events:
        if _classifies(e, family, t):
            return e
    return None


def _failed_rep(events: Sequence[Mapping[str, Any]]):
    evals = [e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    if not evals:
        return None
    failures = [e for e in evals if float(e["net_mfe_pct"]) <= 0]
    if failures:
        return max(failures, key=lambda x: float(x["net_mfe_pct"]))
    return min(evals, key=lambda x: float(x["net_mfe_pct"]))


def _signature_match(markers: set[str], required: Sequence[str], forbidden: Sequence[str]) -> bool:
    return all(x in markers for x in required) and all(x not in markers for x in forbidden)


def _mine_family(
    positives: Sequence[Mapping[str, Any]], negatives: Sequence[Mapping[str, Any]], *,
    min_support: int, max_required: int, max_forbidden: int,
    top_positive_markers: int, top_negative_markers: int, top_signatures: int,
) -> dict[str, Any]:
    psets = [set(r.get("markers", ())) for r in positives]
    nsets = [set(r.get("markers", ())) for r in negatives]
    universe = sorted(set().union(*(psets + nsets))) if (psets or nsets) else []
    p_n = len(psets)
    n_n = len(nsets)
    base_precision = p_n / (p_n + n_n) if (p_n + n_n) else 0.0

    marker_stats = []
    for m in universe:
        pc = sum(m in s for s in psets)
        nc = sum(m in s for s in nsets)
        pp = pc / p_n if p_n else 0.0
        np = nc / n_n if n_n else 0.0
        marker_stats.append({
            "marker": m, "positive_count": pc, "negative_count": nc,
            "positive_prevalence": pp, "negative_prevalence": np,
            "lift_delta": pp - np,
        })
    pos_markers = [
        r["marker"] for r in sorted(marker_stats, key=lambda r: (r["lift_delta"], r["positive_count"]), reverse=True)
        if r["positive_count"] >= min_support and r["lift_delta"] > 0
    ][:top_positive_markers]
    neg_markers = [
        r["marker"] for r in sorted(marker_stats, key=lambda r: (r["negative_prevalence"] - r["positive_prevalence"], r["negative_count"]), reverse=True)
        if r["negative_count"] >= min_support and r["negative_prevalence"] > r["positive_prevalence"]
    ][:top_negative_markers]

    candidates = []
    forbidden_options = [()]
    for k in range(1, max_forbidden + 1):
        forbidden_options.extend(combinations(neg_markers, k))
    for rk in range(1, max_required + 1):
        for req in combinations(pos_markers, rk):
            for forb in forbidden_options:
                if set(req) & set(forb):
                    continue
                pm = [i for i, s in enumerate(psets) if _signature_match(s, req, forb)]
                nm = [i for i, s in enumerate(nsets) if _signature_match(s, req, forb)]
                total = len(pm) + len(nm)
                if total < min_support or len(pm) < max(3, min_support // 3):
                    continue
                precision = len(pm) / total
                recall = len(pm) / p_n if p_n else 0.0
                if precision <= base_precision or recall <= 0:
                    continue
                candidates.append({
                    "required": list(req), "forbidden": list(forb),
                    "discovery_positive_support": len(pm),
                    "discovery_negative_support": len(nm),
                    "discovery_total_support": total,
                    "discovery_precision": precision,
                    "discovery_recall": recall,
                    "discovery_base_precision": base_precision,
                })
    candidates.sort(key=lambda r: (
        r["discovery_precision"], r["discovery_recall"], r["discovery_positive_support"],
        -len(r["required"]), -len(r["forbidden"])
    ), reverse=True)

    dedup = []
    seen = set()
    for r in candidates:
        key = (tuple(r["required"]), tuple(r["forbidden"]))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
        if len(dedup) >= top_signatures:
            break
    return {
        "positive_count": p_n, "negative_count": n_n, "base_precision": base_precision,
        "top_positive_markers": [r for r in marker_stats if r["marker"] in pos_markers],
        "top_negative_markers": [r for r in marker_stats if r["marker"] in neg_markers],
        "candidates": dedup,
    }


def _candidate_id(family: str, i: int) -> str:
    return f"MG_V6_{family}_{i:03d}"


def _scan_validation(
    *, source_name: str, params: CandidateParams, prior_window: int,
    buy_fee_pct: float, sell_fee_pct: float,
    thresholds: Mapping[str, Any], candidates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    matched: dict[str, list[dict[str, Any]]] = {cid: [] for cid in candidates}
    positive_day_keys: set[tuple[str, str]] = set()
    captured_positive_day_keys: set[tuple[str, str]] = set()
    all_day_keys: set[tuple[str, str]] = set()
    packet_count = 0

    for date, ticker, events in _iter_source_ticker_days(
        source_name=source_name, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    ):
        packet_count += 1
        key = (date, ticker)
        all_day_keys.add(key)
        day_positive = any(_classifies(e, "ANY_POSITIVE", thresholds) for e in events)
        if day_positive:
            positive_day_keys.add(key)
        seen: set[str] = set()
        day_profitable_candidate = False
        for e in events:
            markers = set(e.get("markers", ()))
            for cid, spec in candidates.items():
                if cid in seen:
                    continue
                if _signature_match(markers, spec["required"], spec["forbidden"]):
                    seen.add(cid)
                    row = {**e, "trading_date": date, "ticker": ticker}
                    matched[cid].append(row)
                    if _classifies(e, "ANY_POSITIVE", thresholds):
                        day_profitable_candidate = True
        if day_profitable_candidate:
            captured_positive_day_keys.add(key)

    by_candidate = {}
    for cid, rows in matched.items():
        family = candidates[cid]["family"]
        fam_hits = sum(_classifies(r, family, thresholds) for r in rows)
        profitable_matches = sum(_classifies(r, "ANY_POSITIVE", thresholds) for r in rows)
        by_candidate[cid] = {
            "metric": _metric(rows),
            "family_label_rate": fam_hits / len(rows) if rows else None,
            "family_label_count": fam_hits,
            "rows_count": len(rows),
            "positive_match_count": profitable_matches,
            "positive_opportunity_capture_rate": (
                profitable_matches / len(positive_day_keys) if positive_day_keys else None
            ),
        }
    return {
        "packet_count": packet_count,
        "ticker_day_count": len(all_day_keys),
        "positive_opportunity_ticker_days": len(positive_day_keys),
        "captured_positive_ticker_days_by_any_candidate": len(captured_positive_day_keys),
        "candidate_results": by_candidate,
    }


def build_report(
    *, source_names: Sequence[str], params: CandidateParams, prior_window: int,
    buy_fee_pct: float, sell_fee_pct: float, min_support: int,
    max_required: int, max_forbidden: int,
    top_positive_markers: int, top_negative_markers: int, top_signatures: int,
    validation_min_support: int,
) -> dict[str, Any]:
    if len(source_names) < 3:
        raise ValueError("V6_REQUIRES_DISCOVERY_PLUS_TWO_VALIDATION_PERIODS")
    discovery_source = source_names[0]
    validation_sources = list(source_names[1:])

    threshold_rows: list[dict[str, Any]] = []
    discovery_packet_count = 0
    discovery_event_count = 0
    for _date, _ticker, events in _iter_source_ticker_days(
        source_name=discovery_source, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    ):
        discovery_packet_count += 1
        for e in events:
            if not e.get("evaluable") or e.get("net_mfe_pct") is None:
                continue
            discovery_event_count += 1
            if float(e["net_mfe_pct"]) > 0:
                threshold_rows.append({
                    "evaluable": True,
                    "net_mfe_pct": e.get("net_mfe_pct"),
                    "pre_peak_mae_pct": e.get("pre_peak_mae_pct"),
                    "first_positive_net_offset_bars": e.get("first_positive_net_offset_bars"),
                    "reward_to_pre_peak_adverse": e.get("reward_to_pre_peak_adverse"),
                    "eod_net_pct": e.get("eod_net_pct"),
                })
    thresholds = _label_thresholds(threshold_rows)

    families = ("FAST_CLEAN", "STRONG_RUNNER", "RETAINED_WINNER", "ANY_POSITIVE")
    pos_by_family: dict[str, list[dict[str, Any]]] = {f: [] for f in families}
    neg_by_family: dict[str, list[dict[str, Any]]] = {f: [] for f in families}
    discovery_ticker_days = 0

    for date, ticker, events in _iter_source_ticker_days(
        source_name=discovery_source, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    ):
        discovery_ticker_days += 1
        for family in families:
            rep = _first_family_rep(events, family, thresholds)
            if rep is not None:
                pos_by_family[family].append({**rep, "trading_date": date, "ticker": ticker})
            else:
                neg = _failed_rep(events)
                if neg is not None:
                    neg_by_family[family].append({**neg, "trading_date": date, "ticker": ticker})

    discovery = {}
    candidate_specs: dict[str, dict[str, Any]] = {}
    for family in families:
        mined = _mine_family(
            pos_by_family[family], neg_by_family[family],
            min_support=min_support, max_required=max_required, max_forbidden=max_forbidden,
            top_positive_markers=top_positive_markers, top_negative_markers=top_negative_markers,
            top_signatures=top_signatures,
        )
        discovery[family] = mined
        for i, c in enumerate(mined["candidates"], start=1):
            cid = _candidate_id(family, i)
            candidate_specs[cid] = {
                "family": family,
                "required": c["required"],
                "forbidden": c["forbidden"],
                "discovery": c,
            }

    validation = {
        s: _scan_validation(
            source_name=s, params=params, prior_window=prior_window,
            buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            thresholds=thresholds, candidates=candidate_specs,
        )
        for s in validation_sources
    }

    candidate_table = []
    for cid, spec in candidate_specs.items():
        period = {s: validation[s]["candidate_results"][cid] for s in validation_sources}
        basic = all(
            int(period[s]["metric"]["evaluable_count"]) >= validation_min_support
            and float(period[s]["metric"]["positive_net_mfe_rate"] or 0.0) > 0.50
            and float(period[s]["metric"]["net_mfe_q50"] or -999.0) > 0.0
            for s in validation_sources
        )
        strict = basic and all(
            float(period[s]["metric"]["net_mfe_q25"] or -999.0) > 0.0
            for s in validation_sources
        )
        candidate_table.append({
            "candidate_id": cid, **spec,
            "validation": period,
            "cross_period_pass": basic,
            "strict_q25_cross_period_pass": strict,
            "min_validation_positive_rate": min(
                float(period[s]["metric"]["positive_net_mfe_rate"] or 0.0) for s in validation_sources
            ),
            "min_validation_median_net_mfe": min(
                float(period[s]["metric"]["net_mfe_q50"] or -999.0) for s in validation_sources
            ),
            "min_validation_q25_net_mfe": min(
                float(period[s]["metric"]["net_mfe_q25"] or -999.0) for s in validation_sources
            ),
        })
    candidate_table.sort(key=lambda r: (
        bool(r["strict_q25_cross_period_pass"]), bool(r["cross_period_pass"]),
        float(r["min_validation_positive_rate"]),
        float(r["min_validation_q25_net_mfe"]),
        float(r["min_validation_median_net_mfe"]),
    ), reverse=True)

    passed = [r for r in candidate_table if r["cross_period_pass"]]
    strict = [r for r in candidate_table if r["strict_q25_cross_period_pass"]]

    return {
        "schema": "A1_TELEGRAM_MG_FULL_UNIVERSE_TRAJECTORY_CONTRAST_V6",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "method": "ALL_5MIN_CAUSAL_STATES__OUTCOME_PATH_CLASS_LABELS__REQUIRED_PLUS_FORBIDDEN_MARKER_CONTRAST__JAN_FEB_EXACT_VALIDATION",
        "source_names": list(source_names),
        "discovery_source": discovery_source,
        "validation_sources": validation_sources,
        "march_2025_oos_touched": False,
        "h_plus_1_used": False,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_discovery_label_only": True,
        "discovery_packet_count": discovery_packet_count,
        "discovery_ticker_day_count": discovery_ticker_days,
        "discovery_all_evaluable_5min_event_count": discovery_event_count,
        "outcome_label_thresholds_frozen_from_discovery": thresholds,
        "discovery_by_family": discovery,
        "candidate_count": len(candidate_table),
        "candidate_table": candidate_table,
        "cross_period_pass_count": len(passed),
        "strict_q25_cross_period_pass_count": len(strict),
        "cross_period_passed_candidate_ids": [r["candidate_id"] for r in passed],
        "strict_q25_cross_period_passed_candidate_ids": [r["candidate_id"] for r in strict],
        "validation": validation,
        "change_policy": "DO_NOT_THRESHOLD_RESCUE_FAILED_SIGNATURES__ADD_DISTINCT_CAUSAL_FAMILIES_ONLY_IF_EVIDENCE_SUPPORTS",
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-telegram-mg-trajectory-contrast-v6")
    p.add_argument("--request-id", required=True)
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prior-window", type=int, default=2)
    p.add_argument("--buy-fee-pct", type=float, required=True)
    p.add_argument("--sell-fee-pct", type=float, required=True)
    p.add_argument("--min-support", type=int, default=30)
    p.add_argument("--validation-min-support", type=int, default=20)
    p.add_argument("--max-required", type=int, default=3)
    p.add_argument("--max-forbidden", type=int, default=1)
    p.add_argument("--top-positive-markers", type=int, default=16)
    p.add_argument("--top-negative-markers", type=int, default=10)
    p.add_argument("--top-signatures", type=int, default=30)
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
        early_checkpoint_bar=a.early_checkpoint_bar, late_lift_min_bar=a.late_lift_min_bar,
    )
    report = build_report(
        source_names=a.source_name, params=params, prior_window=a.prior_window,
        buy_fee_pct=a.buy_fee_pct, sell_fee_pct=a.sell_fee_pct,
        min_support=a.min_support, validation_min_support=a.validation_min_support,
        max_required=a.max_required, max_forbidden=a.max_forbidden,
        top_positive_markers=a.top_positive_markers, top_negative_markers=a.top_negative_markers,
        top_signatures=a.top_signatures,
    )
    report["request_id"] = a.request_id
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "pass": True,
        "candidate_count": report["candidate_count"],
        "cross_period_pass_count": report["cross_period_pass_count"],
        "strict_q25_cross_period_pass_count": report["strict_q25_cross_period_pass_count"],
        "discovery_event_count": report["discovery_all_evaluable_5min_event_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
