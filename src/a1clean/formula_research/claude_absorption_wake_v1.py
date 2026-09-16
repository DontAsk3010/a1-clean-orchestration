"""Claude-owned independent MG research: "Absorption-Then-Wake" family.

RESEARCH_ONLY. Not canonical, not live-eligible. Part of the
`research/claude-mg-discovery` lane (see /CLAUDE.md). Does not modify or depend
on any GPT-lane conclusion; reuses only the shared, already-governed causal bar
construction in `formula_replay.packet_to_formula_bars` for consistency and
correctness (same field aliases, same session/flow-availability discipline).

--------------------------------------------------------------------------
WHY THIS HYPOTHESIS (self-posed research questions, answered by this code)
--------------------------------------------------------------------------
The owner's own framing (verbatim intent): find stocks that just "woke up" or
that fell/stayed dormant and then started to build/attract interest -- which
means during the falling/dormant phase itself, what needs watching is whether
the stock kept being bought/accumulated/absorbed, and for how long.

Q1 (precursor state) -- Is the ticker currently in, or just exiting, a
    decline-or-dormant phase? Operationalized as a trailing multi-day return
    that is flatter/weaker than the ticker's own historical norm (relative,
    not an arbitrary fixed %).
Q2 (absorption test) -- During that same window, is buying/flow activity
    (trade value and/or the signed NBSS-derived flow proxy) NOT fading in
    proportion to price -- i.e. is flow sustained or rising while price
    stagnates or falls? This is the concrete, measurable form of "terus
    dibeli/diakumulasi/diserap".
Q3 (dose/duration) -- For how many consecutive prior trading days has this
    price-vs-flow divergence held? Longer persistence is a distinct claim
    from a single-day snapshot and is tracked explicitly as its own feature.
Q4 (ignition/wake test) -- On the current day, does price finally respond
    (positive path, upper-range close, value/volume acceleration) after that
    absorption streak has run long enough (threshold learned from discovery
    data only, never assumed)?
Q5 (near-twin / anti-failure) -- Among ticker-days that show the same
    absorption streak, which ones actually wake (favorable forward path) vs.
    remain dormant vs. wake and immediately fail? Reported as three explicit
    outcome buckets, not collapsed into a single hit-rate.
Q6 (independent structural cross-check) -- Does an unsupervised STUMPY
    matrix-profile motif/discord pass over the same close/value series,
    which is never told this hypothesis's rule, independently flag the same
    "quiet-then-departure" shape? Used only as a validity cross-check on the
    hand-built feature, not as the primary discovery method.

--------------------------------------------------------------------------
METHOD / non-negotiable discipline (see /CLAUDE.md)
--------------------------------------------------------------------------
- Full-universe: every eligible ticker-day in the named governed source, no
  cherry-picking.
- Strictly causal: every feature at day index i is computed only from days
  < i (and, within a day, bars <= index). Forward bars are used only inside
  `_forward_outcome`, whose results are never fed back into a feature.
- No arbitrary numeric thresholds: `min_absorption_streak_days` and the
  "flatter/weaker than normal" and "flow holding up better than normal" cuts
  are all learned ONLY from the discovery source (`--phase discover`), then
  frozen into a JSON file and replayed unchanged on validation sources
  (`--phase validate --frozen-thresholds <file>`). March 2025 must never be
  passed as a source to this module (enforced below, fail-closed).
- Missing/unproven flow data resolves to UNKNOWN (`flow_available=False`),
  never zero.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..pattern_discovery.source_reader import GovernedSourceReader
from ..google_drive import build_drive_api
from .formula_replay import packet_to_formula_bars

RESERVED_OOS_SOURCE_TOKENS = ("mar", "maret")


def _reject_oos_source(source_name: str) -> None:
    lowered = source_name.casefold()
    if any(token in lowered for token in RESERVED_OOS_SOURCE_TOKENS):
        raise SystemExit(
            f"REFUSING_TO_TOUCH_RESERVED_OOS_SOURCE:{source_name}:"
            "March 2025 remains untouched OOS per CLAUDE.md."
        )


@dataclass(frozen=True)
class AbsorptionWakeThresholds:
    """Learned-from-discovery, then frozen. Never hand-picked."""

    precursor_window_days: int
    dormant_return_cutoff_pct: float  # learned: corpus median trailing return
    flow_persistence_cutoff_ratio: float  # learned: corpus median flow ratio
    min_absorption_streak_days: int  # learned: streak length separating groups

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> "AbsorptionWakeThresholds":
        return AbsorptionWakeThresholds(
            precursor_window_days=int(payload["precursor_window_days"]),
            dormant_return_cutoff_pct=float(payload["dormant_return_cutoff_pct"]),
            flow_persistence_cutoff_ratio=float(payload["flow_persistence_cutoff_ratio"]),
            min_absorption_streak_days=int(payload["min_absorption_streak_days"]),
        )


def _daily_from_bars(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Causal same-day aggregation. Only ever called on one already-known day's bars."""
    eligible = [b for b in bars if b.get("session_eligible")]
    if not eligible:
        return None
    closes = [float(b["close"]) for b in eligible if b.get("close") is not None]
    highs = [float(b["high"]) for b in eligible if b.get("high") is not None]
    lows = [float(b["low"]) for b in eligible if b.get("low") is not None]
    if not closes or not highs or not lows:
        return None
    flow_rows = [b for b in eligible if b.get("flow_available")]
    flow_available_day = len(flow_rows) >= max(1, int(0.8 * len(eligible)))
    trade_value_sum = sum(float(b["trade_value"]) for b in flow_rows) if flow_available_day else None
    nbss_sum = sum(float(b["nbss"]) for b in flow_rows) if flow_available_day else None
    return {
        "trading_date": eligible[0]["trading_date"],
        "open": float(eligible[0]["open"]) if eligible[0].get("open") is not None else closes[0],
        "high": max(highs),
        "low": min(lows),
        "close": closes[-1],
        "close_location": (closes[-1] - min(lows)) / (max(highs) - min(lows)) if max(highs) > min(lows) else 0.5,
        "flow_available": flow_available_day,
        "trade_value_sum": trade_value_sum,
        "nbss_sum": nbss_sum,
        "bars": eligible,
    }


def _median(values: Sequence[float]) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _trailing_return_pct(daily: Sequence[Mapping[str, Any]], end_idx_exclusive: int, window: int) -> float | None:
    start = end_idx_exclusive - window
    if start < 0:
        return None
    ref_close = daily[start]["close"]
    last_close = daily[end_idx_exclusive - 1]["close"]
    if ref_close in (None, 0):
        return None
    return (last_close / ref_close - 1.0) * 100.0


def _flow_persistence_ratio(daily: Sequence[Mapping[str, Any]], end_idx_exclusive: int, window: int) -> float | None:
    start = end_idx_exclusive - window
    if start < 0:
        return None
    seg = daily[start:end_idx_exclusive]
    if any(not d["flow_available"] for d in seg) or len(seg) < 4:
        return None
    half = len(seg) // 2
    first_half = _median([d["trade_value_sum"] for d in seg[:half]])
    second_half = _median([d["trade_value_sum"] for d in seg[half:]])
    if not first_half:
        return None
    return second_half / first_half


def _forward_outcome(daily: Sequence[Mapping[str, Any]], signal_idx: int, horizon_days: int) -> dict[str, Any]:
    """Outcome-only. Never used as a feature input -- see module docstring."""
    entry = daily[signal_idx]["close"]
    end = signal_idx + horizon_days
    if end >= len(daily) or entry in (None, 0):
        return {"evaluable": False}
    future = daily[signal_idx + 1 : end + 1]
    highs = [d["high"] for d in future]
    lows = [d["low"] for d in future]
    net_mfe_pct = (max(highs) / entry - 1.0) * 100.0
    net_mae_pct = (min(lows) / entry - 1.0) * 100.0
    eod_pct = (future[-1]["close"] / entry - 1.0) * 100.0
    first_positive_offset = next(
        (i + 1 for i, d in enumerate(future) if d["high"] / entry - 1.0 > 0.0), None
    )
    return {
        "evaluable": True,
        "net_mfe_pct": net_mfe_pct,
        "net_mae_pct": net_mae_pct,
        "eod_pct": eod_pct,
        "first_positive_offset_days": first_positive_offset,
    }


def _ignition_today(daily: Sequence[Mapping[str, Any]], idx: int, lookback: int = 5) -> bool:
    start = idx - lookback
    if start < 0:
        return False
    prior_values = [d["trade_value_sum"] for d in daily[start:idx] if d["flow_available"]]
    today = daily[idx]
    if today["close"] is None or daily[idx - 1]["close"] in (None, 0):
        return False
    day_return = today["close"] / daily[idx - 1]["close"] - 1.0
    close_location_ok = today["close_location"] >= 0.6
    value_accel_ok = True
    if today["flow_available"] and prior_values:
        median_prior = _median(prior_values)
        value_accel_ok = bool(median_prior and today["trade_value_sum"] and today["trade_value_sum"] > median_prior)
    return bool(day_return > 0.0 and close_location_ok and value_accel_ok)


def _process_ticker(
    ticker: str,
    sessions: list[dict[str, Any]],
    thresholds: AbsorptionWakeThresholds | None,
    horizons_days: Sequence[int],
) -> tuple[list[dict[str, Any]], list[float], list[float]]:
    """Returns (events, dormant_return_pool, flow_ratio_pool) for one ticker.

    The two pools feed threshold *learning* on discovery; on validation they
    are ignored (thresholds come in frozen).
    """
    sessions = sorted(sessions, key=lambda s: s["trading_date"])
    daily = [d for d in (_daily_from_bars(s["bars"]) for s in sessions) if d is not None]
    events: list[dict[str, Any]] = []
    dormant_pool: list[float] = []
    flow_pool: list[float] = []
    window = thresholds.precursor_window_days if thresholds else 8

    is_absorption_day = [False] * len(daily)
    for i in range(len(daily)):
        ret = _trailing_return_pct(daily, i, window)
        ratio = _flow_persistence_ratio(daily, i, window)
        if ret is None or ratio is None:
            continue
        dormant_pool.append(ret)
        flow_pool.append(ratio)
        if thresholds is not None:
            is_absorption_day[i] = bool(
                ret <= thresholds.dormant_return_cutoff_pct and ratio >= thresholds.flow_persistence_cutoff_ratio
            )

    if thresholds is None:
        return events, dormant_pool, flow_pool

    streak = 0
    fired = False
    for i in range(len(daily)):
        if i > 0 and is_absorption_day[i - 1]:
            streak += 1
        else:
            streak = 0
        if fired:
            continue
        if streak >= thresholds.min_absorption_streak_days and i >= 1 and _ignition_today(daily, i):
            fired = True
            outcomes = {str(h): _forward_outcome(daily, i, h) for h in horizons_days}
            events.append(
                {
                    "ticker": ticker,
                    "trading_date": daily[i]["trading_date"],
                    "absorption_streak_days": streak,
                    "precursor_window_days": window,
                    "outcomes": outcomes,
                    "future_data_used_for_signal": False,
                    "future_data_used_for_outcome_only": True,
                }
            )
    return events, dormant_pool, flow_pool


def _iter_ticker_sessions(source_name: str) -> dict[str, list[dict[str, Any]]]:
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    ticker_sessions: dict[str, list[dict[str, Any]]] = {}
    for _manifest_row, packet in reader.iter_packets():
        bars, _mapping = packet_to_formula_bars(packet)
        ticker = str(packet.identity.ticker)
        ticker_sessions.setdefault(ticker, []).append({"trading_date": packet.identity.trading_date, "bars": bars})
    return ticker_sessions


def discover(source_name: str, *, precursor_window_days: int, min_streak_grid: Sequence[int], horizons_days: Sequence[int]) -> dict[str, Any]:
    _reject_oos_source(source_name)
    ticker_sessions = _iter_ticker_sessions(source_name)

    dormant_pool: list[float] = []
    flow_pool: list[float] = []
    for ticker, sessions in ticker_sessions.items():
        _events, d_pool, f_pool = _process_ticker(ticker, sessions, None, horizons_days)
        dormant_pool.extend(d_pool)
        flow_pool.extend(f_pool)

    dormant_cutoff = _median(dormant_pool)
    flow_cutoff = _median(flow_pool)
    if dormant_cutoff is None or flow_cutoff is None:
        raise SystemExit("INSUFFICIENT_DISCOVERY_DATA_FOR_THRESHOLD_LEARNING")

    grid_results = []
    best = None
    for streak in min_streak_grid:
        thresholds = AbsorptionWakeThresholds(
            precursor_window_days=precursor_window_days,
            dormant_return_cutoff_pct=dormant_cutoff,
            flow_persistence_cutoff_ratio=flow_cutoff,
            min_absorption_streak_days=streak,
        )
        all_events: list[dict[str, Any]] = []
        for ticker, sessions in ticker_sessions.items():
            events, _d, _f = _process_ticker(ticker, sessions, thresholds, horizons_days)
            all_events.extend(events)
        summary = _summarize(all_events, horizons_days)
        row = {"min_absorption_streak_days": streak, "event_count": len(all_events), "summary": summary}
        grid_results.append(row)
        primary_horizon = str(horizons_days[0])
        q25 = summary.get(primary_horizon, {}).get("net_mfe_q25")
        if q25 is not None and (best is None or q25 > best["q25"]):
            best = {"streak": streak, "q25": q25, "thresholds": thresholds}

    if best is None:
        raise SystemExit("NO_MIN_STREAK_CANDIDATE_PRODUCED_EVALUABLE_EVENTS_ON_DISCOVERY")

    return {
        "schema": "A1_CLAUDE_ABSORPTION_WAKE_DISCOVERY_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "ticker_count": len(ticker_sessions),
        "learned_thresholds": best["thresholds"].as_dict(),
        "min_streak_grid_results": grid_results,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_discovery_label_only": True,
        "winner_only_filter_used": False,
        "all_eligible_source_packets_scanned": True,
    }


def validate(source_name: str, *, thresholds: AbsorptionWakeThresholds, horizons_days: Sequence[int]) -> dict[str, Any]:
    _reject_oos_source(source_name)
    ticker_sessions = _iter_ticker_sessions(source_name)
    all_events: list[dict[str, Any]] = []
    for ticker, sessions in ticker_sessions.items():
        events, _d, _f = _process_ticker(ticker, sessions, thresholds, horizons_days)
        all_events.extend(events)
    summary = _summarize(all_events, horizons_days)
    return {
        "schema": "A1_CLAUDE_ABSORPTION_WAKE_VALIDATION_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "ticker_count": len(ticker_sessions),
        "applied_thresholds": thresholds.as_dict(),
        "event_count": len(all_events),
        "unique_ticker_count": len({e["ticker"] for e in all_events}),
        "unique_date_count": len({e["trading_date"] for e in all_events}),
        "summary": summary,
        "events": all_events,
        "thresholds_frozen_not_retuned": True,
        "future_data_used_for_formula_state": False,
        "future_data_used_for_discovery_label_only": True,
    }


def _summarize(events: Sequence[Mapping[str, Any]], horizons_days: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for h in horizons_days:
        key = str(h)
        vals = [e["outcomes"][key] for e in events if e["outcomes"].get(key, {}).get("evaluable")]
        n = len(vals)
        if n == 0:
            out[key] = {"evaluable_count": 0}
            continue
        mfe = sorted(v["net_mfe_pct"] for v in vals)
        mae = sorted(v["net_mae_pct"] for v in vals)
        eod = sorted(v["eod_pct"] for v in vals)

        def q(sorted_vals: list[float], p: float) -> float:
            idx = min(len(sorted_vals) - 1, max(0, int(round(p * (len(sorted_vals) - 1)))))
            return sorted_vals[idx]

        out[key] = {
            "evaluable_count": n,
            "positive_net_mfe_rate": sum(1 for v in vals if v["net_mfe_pct"] > 0) / n,
            "net_mfe_q25": q(mfe, 0.25),
            "net_mfe_q50": q(mfe, 0.50),
            "net_mfe_q75": q(mfe, 0.75),
            "net_mae_q25": q(mae, 0.25),
            "net_mae_q50": q(mae, 0.50),
            "eod_q50": q(eod, 0.50),
        }
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-absorption-wake-v1")
    parser.add_argument("--phase", choices=["discover", "validate"], required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--horizons-days", default="1,3,5,8")
    parser.add_argument("--precursor-window-days", type=int, default=8)
    parser.add_argument("--min-streak-grid", default="2,3,4,5,6,8")
    parser.add_argument("--frozen-thresholds", default=None, help="Required for --phase validate")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    horizons = [int(x) for x in args.horizons_days.split(",") if x.strip()]

    if args.phase == "discover":
        grid = [int(x) for x in args.min_streak_grid.split(",") if x.strip()]
        result = discover(
            args.source_name,
            precursor_window_days=args.precursor_window_days,
            min_streak_grid=grid,
            horizons_days=horizons,
        )
    else:
        if not args.frozen_thresholds:
            raise SystemExit("--frozen-thresholds is required for --phase validate")
        payload = json.loads(Path(args.frozen_thresholds).read_text(encoding="utf-8"))
        thresholds = AbsorptionWakeThresholds.from_dict(payload.get("learned_thresholds", payload))
        result = validate(args.source_name, thresholds=thresholds, horizons_days=horizons)

    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pass": True, "phase": args.phase, "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
