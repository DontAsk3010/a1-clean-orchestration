from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams
from .telegram_mg_behavior_topology_v2 import _net_return_pct
from .telegram_mg_multihypothesis_v8 import _daily, _event_features, _finite, _outcome
from .telegram_mg_multihypothesis_v8b import _marker_set
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict
from .telegram_mg_replay import _dynamic_targets, evaluate_mg_packet


def _params() -> CandidateParams:
    return CandidateParams(
        effort_lookback=5,
        progress_lookback=5,
        high_lookback=5,
        recovery_lookback=5,
        low_stabilization_bars=3,
        early_checkpoint_bar=30,
        late_lift_min_bar=120,
    )


def _hhmm(ts: Any) -> str | None:
    text = str(ts or "")
    if "T" not in text:
        return None
    return text.split("T", 1)[1][:5]


def _target_hit(
    bars: Sequence[Mapping[str, Any]], signal_index: int, target: float | None
) -> tuple[bool | None, str | None]:
    if target is None:
        return None, None
    for row in bars[signal_index + 1 :]:
        high = _finite(row.get("high"))
        if high is not None and high >= float(target):
            return True, _hhmm(row.get("timestamp"))
    return False, None


def _target_net(
    entry: float | None, target: float | None, step: float | None,
    buy_fee_pct: float, sell_fee_pct: float,
) -> float | None:
    if entry is None or target is None or step is None or entry <= 0:
        return None
    executable_exit = max(0.0, float(target) - float(step))
    return _net_return_pct(float(entry), executable_exit, buy_fee_pct, sell_fee_pct)


def _formula_matches(markers: set[str], formulas: Sequence[Mapping[str, Any]]) -> list[str]:
    hits: list[str] = []
    for row in formulas:
        req = [str(x) for x in row.get("required", [])]
        if req and all(x in markers for x in req):
            hits.append(str(row.get("id") or "UNNAMED"))
    return hits


def build_replay(
    *,
    formula_pack: Mapping[str, Any],
    target_source: str,
    target_date: str | None,
    prior_days: int,
    buy_fee_pct: float,
    sell_fee_pct: float,
) -> dict[str, Any]:
    thresholds = formula_pack.get("feature_thresholds_frozen_from_discovery")
    formulas = formula_pack.get("formulas")
    if not isinstance(thresholds, Mapping):
        raise ValueError("V8_REPLAY_FEATURE_THRESHOLDS_MISSING")
    if not isinstance(formulas, list) or not formulas:
        raise ValueError("V8_REPLAY_FORMULAS_MISSING")

    sources = [s for s in _discover_sources_strict() if not s.get("reserved_oos")]
    names = [str(s["source_name"]) for s in sources]
    if target_source not in names:
        raise ValueError(f"V8_REPLAY_TARGET_SOURCE_NOT_AVAILABLE:{target_source}")
    selected_sources = sources[: names.index(target_source) + 1]

    api = build_drive_api(read_write=False)
    params = _params()
    history_daily: dict[str, list[Any]] = defaultdict(list)
    history_bars: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    snapshots: dict[str, list[dict[str, Any]]] = defaultdict(list)
    observed_slots: set[str] = set()
    target_dates_seen: set[str] = set()
    target_ticker_days = 0

    for src in selected_sources:
        source_name = str(src["source_name"])
        reader = GovernedSourceReader(api, source_name=source_name)
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(b) for b in all_bars if b.get("session_eligible")]
            if not bars:
                continue
            ticker = str(packet.identity.ticker)
            date = str(packet.identity.trading_date)
            hd = history_daily.get(ticker, [])[-prior_days:]
            hb = history_bars.get(ticker, [])[-prior_days:]

            is_target = source_name == target_source and (target_date is None or date == target_date)
            if is_target:
                target_ticker_days += 1
                target_dates_seen.add(date)
                mgrows = evaluate_mg_packet(bars, params)
                if len(hd) >= 2 and len(hb) >= 2:
                    prev_close = float(hd[-1].close) if hd else None
                    for i, mg in enumerate(mgrows):
                        if not mg.get("publication_slot"):
                            continue
                        slot = _hhmm(mg.get("timestamp"))
                        if slot is None:
                            continue
                        observed_slots.add(slot)
                        feat = _event_features(bars, i, hd, hb)
                        if not feat:
                            continue
                        event = {"features": feat}
                        markers = _marker_set(event, thresholds)
                        matched_ids = _formula_matches(markers, formulas)
                        if not matched_ids:
                            continue

                        price = _finite(bars[i].get("close"))
                        chg = None if price is None or prev_close is None or prev_close <= 0 else (price / prev_close - 1.0) * 100.0
                        tp1, tp2, _target_step = _dynamic_targets(bars, i, 5)
                        outcome = _outcome(bars, i, buy_fee_pct, sell_fee_pct)
                        entry = _finite(outcome.get("entry_proxy"))
                        step = _finite(outcome.get("step_proxy"))
                        tp1_hit, tp1_time = _target_hit(bars, i, tp1)
                        tp2_hit, tp2_time = _target_hit(bars, i, tp2)
                        snapshots[f"{date} {slot}"].append({
                            "date": date,
                            "time": slot,
                            "code": ticker,
                            "price": price,
                            "chg_pct": chg,
                            "tp1": tp1,
                            "tp2": tp2,
                            "formula_ids": matched_ids,
                            "entry_proxy": entry,
                            "tp1_hit": tp1_hit,
                            "tp1_hit_time": tp1_time,
                            "tp1_net_pct": _target_net(entry, tp1, step, buy_fee_pct, sell_fee_pct) if tp1_hit else None,
                            "tp2_hit": tp2_hit,
                            "tp2_hit_time": tp2_time,
                            "tp2_net_pct": _target_net(entry, tp2, step, buy_fee_pct, sell_fee_pct) if tp2_hit else None,
                            "net_mfe_pct": outcome.get("net_mfe_pct"),
                            "mae_pct": outcome.get("mae_pct"),
                            "eod_net_pct": outcome.get("eod_net_pct"),
                        })

            d = _daily(bars, date)
            if d is not None:
                history_daily[ticker].append(d)
                history_daily[ticker] = history_daily[ticker][-prior_days:]
                history_bars[ticker].append(bars)
                history_bars[ticker] = history_bars[ticker][-prior_days:]

    ordered = []
    for date in sorted(target_dates_seen):
        for slot in sorted(observed_slots):
            rows = sorted(snapshots.get(f"{date} {slot}", []), key=lambda r: r["code"])
            ordered.append({"date": date, "time": slot, "rows": rows})

    unique_events = sum(len(s["rows"]) for s in ordered)
    unique_tickers = sorted({r["code"] for s in ordered for r in s["rows"]})
    return {
        "schema": "A1_TELEGRAM_MG_V8_SURVIVOR_REPLAY_V1",
        "status": "RESEARCH_REPLAY_NOT_CANONICAL",
        "target_source": target_source,
        "target_date": target_date,
        "target_dates_seen": sorted(target_dates_seen),
        "target_ticker_days": target_ticker_days,
        "formula_ids": [str(x.get("id")) for x in formulas],
        "formula_mode": "UNION_ANY_SURVIVOR_TRUE_AT_CURRENT_SNAPSHOT",
        "recompute_each_publication_snapshot": True,
        "repeat_ticker_if_still_qualifies": True,
        "live_contract_columns": ["CODE", "PRICE", "CHG%", "TP-1", "TP-2"],
        "test_only_columns": ["ENTRY_PROXY", "TP1_HIT", "TP1_HIT_TIME", "TP1_NET_PCT", "TP2_HIT", "TP2_HIT_TIME", "TP2_NET_PCT", "NET_MFE_PCT", "MAE_PCT", "EOD_NET_PCT"],
        "future_data_used_for_formula_state": False,
        "future_data_used_for_replay_outcome_only": True,
        "snapshot_count": len(ordered),
        "signal_rows": unique_events,
        "unique_tickers": unique_tickers,
        "snapshots": ordered,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--formula-pack", required=True)
    p.add_argument("--target-source", required=True)
    p.add_argument("--target-date")
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    pack = json.loads(Path(a.formula_pack).read_text(encoding="utf-8"))
    report = build_replay(
        formula_pack=pack,
        target_source=a.target_source,
        target_date=a.target_date,
        prior_days=a.prior_days,
        buy_fee_pct=a.buy_fee_pct,
        sell_fee_pct=a.sell_fee_pct,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
