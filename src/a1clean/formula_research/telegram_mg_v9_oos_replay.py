from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .telegram_mg_behavior_topology_v2 import _net_return_pct, _observed_step
from .telegram_mg_multihypothesis_v8 import _daily, _finite
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict
from .telegram_mg_multihypothesis_v8e import _prefix_series
from .telegram_mg_replay import _dynamic_targets, _is_publication_slot
from . import telegram_mg_streaming_multilogic_v9 as core


def _hhmm(ts: Any) -> str | None:
    text = str(ts or "")
    if "T" not in text:
        return None
    return text.split("T", 1)[1][:5]


def _formula_hits(precursors: set[str], ignitions: set[str], formulas: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        str(f["id"])
        for f in formulas
        if str(f.get("precursor")) in precursors and str(f.get("ignition")) in ignitions
    ]


def _target_hit(bars: Sequence[Mapping[str, Any]], index: int, target: float | None) -> tuple[bool | None, str | None]:
    if target is None:
        return None, None
    for row in bars[index + 1:]:
        high = _finite(row.get("high"))
        if high is not None and float(high) >= float(target):
            return True, _hhmm(row.get("timestamp"))
    return False, None


def _target_net(entry: float | None, target: float | None, step: float | None, buy_fee: float, sell_fee: float) -> float | None:
    if entry is None or target is None or step is None or entry <= 0:
        return None
    exit_proxy = max(0.0, float(target) - float(step))
    return _net_return_pct(float(entry), exit_proxy, buy_fee, sell_fee)


def _entry_proxy(bars: Sequence[Mapping[str, Any]], index: int) -> tuple[float | None, float | None]:
    if index + 1 >= len(bars):
        return None, None
    step = _observed_step(bars, index)
    nxt = _finite(bars[index + 1].get("open"))
    if step is None or nxt is None or nxt <= 0:
        return None, None
    return float(nxt) + float(step), float(step)


def build_replay(
    *, formula_pack: Mapping[str, Any], target_source: str | None,
    prior_days: int, buy_fee: float, sell_fee: float,
) -> dict[str, Any]:
    formulas = formula_pack.get("formulas")
    if not isinstance(formulas, list) or not formulas:
        raise ValueError("V9_OOS_FORMULAS_MISSING")

    sources = _discover_sources_strict()
    reserved = [s for s in sources if s.get("reserved_oos")]
    if target_source is None:
        if not reserved:
            raise ValueError("V9_OOS_RESERVED_SOURCE_MISSING")
        target_source = str(reserved[0]["source_name"])
    names = [str(s["source_name"]) for s in sources]
    if target_source not in names:
        raise ValueError(f"V9_OOS_TARGET_SOURCE_NOT_FOUND:{target_source}")
    selected_sources = sources[:names.index(target_source) + 1]

    api = build_drive_api(read_write=False)
    history_daily: dict[str, list[Any]] = defaultdict(list)
    history_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)
    snapshot_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    observed_slots: dict[str, set[str]] = defaultdict(set)
    target_dates: set[str] = set()
    target_ticker_days = 0

    for src in selected_sources:
        source = str(src["source_name"])
        reader = GovernedSourceReader(api, source_name=source)
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(b) for b in all_bars if b.get("session_eligible")]
            if not bars:
                continue
            ticker = str(packet.identity.ticker)
            date = str(packet.identity.trading_date)
            hd = history_daily.get(ticker, [])[-prior_days:]
            hp = history_prefix.get(ticker, [])[-prior_days:]
            current_prefix = _prefix_series(bars)

            if source == target_source:
                target_ticker_days += 1
                target_dates.add(date)
                precursors = core._precursor_states(hd)
                suffix_high, suffix_low, final_close = core._suffix_extremes(bars)
                prev_close = float(hd[-1].close) if hd else None
                if precursors and len(hp) >= 3:
                    for i, bar in enumerate(bars):
                        if not _is_publication_slot(bar.get("timestamp")):
                            continue
                        slot = _hhmm(bar.get("timestamp"))
                        if slot is None:
                            continue
                        observed_slots[date].add(slot)
                        ignitions = core._ignition_states(current_prefix, hp, i)
                        if not ignitions:
                            continue
                        hits = _formula_hits(precursors, ignitions, formulas)
                        if not hits:
                            continue

                        price = _finite(bar.get("close"))
                        chg = None if price is None or prev_close is None or prev_close <= 0 else (float(price) / prev_close - 1.0) * 100.0
                        tp1, tp2, _ = _dynamic_targets(bars, i, 5)
                        entry, step = _entry_proxy(bars, i)
                        outcome = core._outcome_quick(
                            bars, i, suffix_high, suffix_low, final_close,
                            buy_fee, sell_fee,
                        )
                        tp1_hit, tp1_time = _target_hit(bars, i, tp1)
                        tp2_hit, tp2_time = _target_hit(bars, i, tp2)
                        snapshot_rows[(date, slot)].append({
                            "code": ticker,
                            "price": price,
                            "chg_pct": chg,
                            "tp1": tp1,
                            "tp2": tp2,
                            "formula_ids": hits,
                            "entry_proxy": entry,
                            "tp1_hit": tp1_hit,
                            "tp1_hit_time": tp1_time,
                            "tp1_net_pct": _target_net(entry, tp1, step, buy_fee, sell_fee) if tp1_hit else None,
                            "tp2_hit": tp2_hit,
                            "tp2_hit_time": tp2_time,
                            "tp2_net_pct": _target_net(entry, tp2, step, buy_fee, sell_fee) if tp2_hit else None,
                            "net_mfe_pct": outcome[0] if outcome else None,
                            "mae_pct": outcome[1] if outcome else None,
                            "eod_net_pct": outcome[2] if outcome else None,
                        })
                else:
                    for bar in bars:
                        if _is_publication_slot(bar.get("timestamp")):
                            slot = _hhmm(bar.get("timestamp"))
                            if slot:
                                observed_slots[date].add(slot)

            d = _daily(bars, date)
            if d is not None:
                history_daily[ticker].append(d)
                history_daily[ticker] = history_daily[ticker][-prior_days:]
                history_prefix[ticker].append(current_prefix)
                history_prefix[ticker] = history_prefix[ticker][-prior_days:]

    snapshots: list[dict[str, Any]] = []
    for date in sorted(target_dates):
        for slot in sorted(observed_slots.get(date, set())):
            rows = sorted(snapshot_rows.get((date, slot), []), key=lambda r: r["code"])
            snapshots.append({"date": date, "time": slot, "rows": rows})

    signal_rows = [r for s in snapshots for r in s["rows"]]
    evaluable = [r for r in signal_rows if r.get("net_mfe_pct") is not None]
    pos = [r for r in evaluable if float(r["net_mfe_pct"]) > 0]
    tp1_eval = [r for r in signal_rows if r.get("tp1_hit") is not None]
    tp2_eval = [r for r in signal_rows if r.get("tp2_hit") is not None]
    return {
        "schema": "A1_TELEGRAM_MG_V9_OOS_REPLAY_V1",
        "status": "RESEARCH_OOS_REPLAY_NOT_CANONICAL",
        "target_source": target_source,
        "formula_ids": [str(f["id"]) for f in formulas],
        "formula_mode": "UNION_ANY_SURVIVOR_TRUE_AT_EACH_CURRENT_SNAPSHOT",
        "target_dates": sorted(target_dates),
        "target_ticker_days": target_ticker_days,
        "snapshot_count": len(snapshots),
        "signal_rows": len(signal_rows),
        "unique_tickers": sorted({str(r["code"]) for r in signal_rows}),
        "positive_net_mfe_rate": (len(pos) / len(evaluable)) if evaluable else None,
        "tp1_hit_rate": (sum(bool(r["tp1_hit"]) for r in tp1_eval) / len(tp1_eval)) if tp1_eval else None,
        "tp2_hit_rate": (sum(bool(r["tp2_hit"]) for r in tp2_eval) / len(tp2_eval)) if tp2_eval else None,
        "live_contract_columns": ["CODE", "PRICE", "CHG%", "TP-1", "TP-2"],
        "recompute_each_publication_snapshot": True,
        "repeat_ticker_if_still_qualifies": True,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "snapshots": snapshots,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--formula-pack", required=True)
    p.add_argument("--target-source")
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    pack = json.loads(Path(a.formula_pack).read_text(encoding="utf-8"))
    report = build_replay(
        formula_pack=pack,
        target_source=a.target_source,
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
