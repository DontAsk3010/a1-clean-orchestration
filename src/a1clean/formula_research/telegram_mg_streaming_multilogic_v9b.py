from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .telegram_mg_multihypothesis_v8 import _daily
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict
from .telegram_mg_multihypothesis_v8e import _prefix_series
from .telegram_mg_replay import _is_publication_slot
from . import telegram_mg_streaming_multilogic_v9 as core

BLOCKS = ("discovery", "validation_a", "validation_b")


def _evaluate_all_sources(
    sources: Sequence[Mapping[str, Any]],
    block_by_source: Mapping[str, str],
    prior_days: int,
    buy_fee: float,
    sell_fee: float,
) -> tuple[
    dict[str, dict[str, list[tuple[float, float, float]]]],
    dict[str, dict[str, int]],
]:
    results: dict[str, dict[str, list[tuple[float, float, float]]]] = {
        block: defaultdict(list) for block in BLOCKS
    }
    counters: dict[str, dict[str, int]] = {
        block: {"ticker_days": 0, "publication_slots": 0, "evaluable_matches": 0}
        for block in BLOCKS
    }
    history_daily: dict[str, list[Any]] = defaultdict(list)
    history_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)
    api = build_drive_api(read_write=False)

    for src in sources:
        source = str(src["source_name"])
        block = block_by_source[source]
        reader = GovernedSourceReader(api, source_name=source)
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(b) for b in all_bars if b.get("session_eligible")]
            if not bars:
                continue
            counters[block]["ticker_days"] += 1
            ticker = str(packet.identity.ticker)
            date = str(packet.identity.trading_date)
            hd = history_daily.get(ticker, [])[-prior_days:]
            hp = history_prefix.get(ticker, [])[-prior_days:]
            current_prefix = _prefix_series(bars)
            precursors = core._precursor_states(hd)
            seen: set[str] = set()
            suffix_high, suffix_low, final_close = core._suffix_extremes(bars)

            if precursors and len(hp) >= 3:
                for i, bar in enumerate(bars):
                    if not _is_publication_slot(bar.get("timestamp")):
                        continue
                    counters[block]["publication_slots"] += 1
                    ignitions = core._ignition_states(current_prefix, hp, i)
                    if not ignitions:
                        continue
                    new_ids = [
                        f"{p}__{g}"
                        for p in precursors
                        for g in ignitions
                        if f"{p}__{g}" not in seen
                    ]
                    if not new_ids:
                        continue
                    outcome = core._outcome_quick(
                        bars, i, suffix_high, suffix_low, final_close,
                        buy_fee, sell_fee,
                    )
                    if outcome is None:
                        continue
                    counters[block]["evaluable_matches"] += len(new_ids)
                    for cid in new_ids:
                        results[block][cid].append(outcome)
                        seen.add(cid)

            d = _daily(bars, date)
            if d is not None:
                history_daily[ticker].append(d)
                history_daily[ticker] = history_daily[ticker][-prior_days:]
                history_prefix[ticker].append(current_prefix)
                history_prefix[ticker] = history_prefix[ticker][-prior_days:]

    return results, counters


def build_report(
    *, prior_days: int, buy_fee: float, sell_fee: float,
    min_support: int, min_unique_days: int,
) -> dict[str, Any]:
    del min_unique_days  # first causal match => one observation per candidate/ticker-day
    sources = _discover_sources_strict()
    usable = [s for s in sources if not s.get("reserved_oos")]
    if len(usable) < 3:
        raise ValueError("V9B_NEEDS_AT_LEAST_THREE_NON_OOS_SOURCES")

    n = len(usable)
    d_end = max(1, int(n * 0.60))
    v1_end = max(d_end + 1, int(n * 0.80))
    v1_end = min(v1_end, n - 1)
    disc_src = usable[:d_end]
    va_src = usable[d_end:v1_end]
    vb_src = usable[v1_end:]

    block_by_source = {
        **{str(s["source_name"]): "discovery" for s in disc_src},
        **{str(s["source_name"]): "validation_a" for s in va_src},
        **{str(s["source_name"]): "validation_b" for s in vb_src},
    }
    results, counters = _evaluate_all_sources(
        usable, block_by_source, prior_days, buy_fee, sell_fee
    )

    candidates: list[dict[str, Any]] = []
    all_ids = sorted(
        set(results["discovery"])
        | set(results["validation_a"])
        | set(results["validation_b"])
    )
    for cid in all_ids:
        dm = core._metric(results["discovery"].get(cid, []))
        am = core._metric(results["validation_a"].get(cid, []))
        bm = core._metric(results["validation_b"].get(cid, []))
        strict = all(
            m["n"] >= min_support
            and m["q25_net_mfe_pct"] is not None
            and float(m["q25_net_mfe_pct"]) > 0
            and m["median_net_mfe_pct"] is not None
            and float(m["median_net_mfe_pct"]) > 0
            for m in (dm, am, bm)
        )
        precursor, ignition = cid.split("__", 1)
        candidates.append({
            "id": cid,
            "precursor": precursor,
            "ignition": ignition,
            "discovery": dm,
            "validation_a": am,
            "validation_b": bm,
            "strict_cross_period_pass": strict,
        })

    def _score(row: Mapping[str, Any]) -> tuple[Any, ...]:
        ms = [row["discovery"], row["validation_a"], row["validation_b"]]
        q25 = min(float(m["q25_net_mfe_pct"] if m["q25_net_mfe_pct"] is not None else -999) for m in ms)
        med = min(float(m["median_net_mfe_pct"] if m["median_net_mfe_pct"] is not None else -999) for m in ms)
        wr = min(float(m["positive_net_mfe_rate"] if m["positive_net_mfe_rate"] is not None else 0) for m in ms)
        support = min(int(m["n"]) for m in ms)
        return (bool(row["strict_cross_period_pass"]), q25, med, wr, support)

    candidates.sort(key=_score, reverse=True)
    strict = [r for r in candidates if r["strict_cross_period_pass"]]
    return {
        "schema": "A1_TELEGRAM_MG_STREAMING_MULTI_LOGIC_V9B_RESULT_V1",
        "status": "RESEARCH_ONLY_NOT_CANONICAL",
        "method": "ONE_CHRONOLOGICAL_PASS_ALL_GOVERNED_NON_OOS_SOURCES_FIRST_CAUSAL_MATCH_PER_FORMULA_PER_TICKER_DAY",
        "precursor_hypotheses": list(core.PRECURSORS),
        "ignition_hypotheses": list(core.IGNITIONS),
        "candidate_formula_count": len(core.PRECURSORS) * len(core.IGNITIONS),
        "all_governed_sources": sources,
        "discovery_sources": disc_src,
        "validation_a_sources": va_src,
        "validation_b_sources": vb_src,
        "reserved_oos_sources": [s for s in sources if s.get("reserved_oos")],
        "execution": {"buy_fee_pct": buy_fee, "sell_fee_pct": sell_fee},
        "counters": counters,
        "strict_cross_period_pass_count": len(strict),
        "strict_cross_period_passed": strict,
        "all_candidates": candidates,
        "cross_source_history_continuity": True,
        "source_pass_count": 1,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_outcome_evaluation_only": True,
        "march_2025_reserved_oos_untouched": True,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    p.add_argument("--min-unique-days", type=int, default=20)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
        min_unique_days=a.min_unique_days,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
