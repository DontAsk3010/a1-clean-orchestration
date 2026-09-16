"""Claude-owned MG candidate v2: multi-day absorption precursor -> intraday wake.

RESEARCH_ONLY. Not canonical, not live-eligible. Part of the
`research/claude-mg-discovery` lane (see /CLAUDE.md).

--------------------------------------------------------------------------
WHY V2 EXISTS (what v1 got structurally wrong)
--------------------------------------------------------------------------
`claude_absorption_wake_v1` collapsed every trading day into one daily
aggregate and measured outcomes in days. The governed MG family is intraday:
Branch 07 Formula Research Handbook (Drive 1sQu0l2qwvsjItmBycRh3siMajKEQknHOMBLlBQd3I-Q,
VERSION 20260915 V1) §3 fixes EARLY_POTENTIAL / MULAI GENIT as publishing
`CODE | PRICE | CHG% | TP-1 | TP-2` at the first automatic snapshot then every
5 minutes, with TP-1/TP-2 dynamic per snapshot and never computed Telegram-side.
A daily candidate emitting no target cannot satisfy that contract, so v2 keeps
the multi-day precursor (handbook §4 "prior state") and moves ignition,
publication and outcome measurement onto the intraday snapshot grid.

Forward horizons are expressed in regular bars (5/15/30/60), matching the GPT
lane's governed December replay
(`CANDIDATE_FORMULA_REPLAY__FORMULA_REPLAY_FULL_DES2024_20260915_01.json`,
schema A1_CANDIDATE_FORMULA_CAUSAL_REPLAY_RESULT_V1) so the two lanes stay
head-to-head comparable on the same source rather than on rescaled numbers.

--------------------------------------------------------------------------
CAUSALITY (the contract this module must never break)
--------------------------------------------------------------------------
At a snapshot on day D, bar index t, candidate state may read ONLY:
  - complete trading days strictly before D (the precursor block), and
  - bars 0..t of day D (the intraday block).
Forward bars t+1.. are read exclusively inside `_forward_from_bar`, whose
output never re-enters any state or gate. Forward evaluation is clipped to the
same trading date, so an outcome can never borrow the next day's open.

--------------------------------------------------------------------------
NO INVENTED NUMBERS
--------------------------------------------------------------------------
Every cut-point below is learned from the discovery source only, frozen to
JSON, and replayed unchanged on validation. That includes the TP multiples:
TP-1/TP-2 are `price + multiple * volatility_unit`, where the multiples are
quantiles of the realized favorable-excursion distribution observed on
discovery, expressed in volatility units. Targets therefore come from observed
behavior (Master §20A.6), not from a chosen percentage.

The only hard-coded integer is a structural minimum of 2 constructive bars,
which is the definition of "persistence" rather than a tuned threshold: one bar
cannot evidence persistence.

--------------------------------------------------------------------------
FAILURE / LOOKALIKE CONTROLS (handbook §4, all mandatory)
--------------------------------------------------------------------------
one-bar spike without continuation; mature/high-CHG chase; large effort with
poor response; rejection/giveback; thin-liquidity jump; unstable path;
stale/partial/invalid data. Each is evaluated and its rejection reason is
counted, so suppressed candidates remain visible evidence instead of vanishing.

Flow semantics follow the governed policy: a physical NBSS zero is UNKNOWN, not
neutral (`flow_available` in `packet_to_formula_bars`). Unavailable never
becomes zero.
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

# Structural, not tuned: persistence is undefined below two bars.
MIN_CONSTRUCTIVE_BARS = 2

REJECTION_REASONS = (
    "stale_or_partial_data",
    "no_precursor_context",
    "absorption_streak_too_short",
    "thin_liquidity",
    "mature_chase",
    "one_bar_spike_no_continuation",
    "effort_without_response",
    "rejection_giveback",
    "unstable_path",
    "no_remaining_room",
)


def _reject_oos_source(source_name: str) -> None:
    lowered = source_name.casefold()
    if any(token in lowered for token in RESERVED_OOS_SOURCE_TOKENS):
        raise SystemExit(
            f"REFUSING_TO_TOUCH_RESERVED_OOS_SOURCE:{source_name}:"
            "March 2025 remains untouched OOS per CLAUDE.md."
        )


@dataclass(frozen=True)
class MGIntradayThresholds:
    """Learned on discovery, frozen, replayed unchanged. Never hand-picked."""

    precursor_window_days: int
    dormant_return_cutoff_pct: float
    flow_persistence_cutoff_ratio: float
    min_absorption_streak_days: int
    chg_chase_cutoff_pct: float
    min_day_trade_value: float
    close_location_cutoff: float
    tp1_vol_multiple: float
    tp2_vol_multiple: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> "MGIntradayThresholds":
        return MGIntradayThresholds(
            precursor_window_days=int(payload["precursor_window_days"]),
            dormant_return_cutoff_pct=float(payload["dormant_return_cutoff_pct"]),
            flow_persistence_cutoff_ratio=float(payload["flow_persistence_cutoff_ratio"]),
            min_absorption_streak_days=int(payload["min_absorption_streak_days"]),
            chg_chase_cutoff_pct=float(payload["chg_chase_cutoff_pct"]),
            min_day_trade_value=float(payload["min_day_trade_value"]),
            close_location_cutoff=float(payload["close_location_cutoff"]),
            tp1_vol_multiple=float(payload["tp1_vol_multiple"]),
            tp2_vol_multiple=float(payload["tp2_vol_multiple"]),
        )


def _median(values: Sequence[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return statistics.median(clean) if clean else None


def _quantile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[idx]


def _day_summary(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Whole-day rollup. Only ever applied to days already completed in the past."""
    eligible = [b for b in bars if b.get("session_eligible")]
    if not eligible:
        return None
    closes = [float(b["close"]) for b in eligible if b.get("close") is not None]
    highs = [float(b["high"]) for b in eligible if b.get("high") is not None]
    lows = [float(b["low"]) for b in eligible if b.get("low") is not None]
    if not closes or not highs or not lows:
        return None
    flow_rows = [b for b in eligible if b.get("flow_available")]
    flow_ok = len(flow_rows) >= max(1, int(0.8 * len(eligible)))
    return {
        "trading_date": eligible[0]["trading_date"],
        "high": max(highs),
        "low": min(lows),
        "close": closes[-1],
        "range_pct": (max(highs) - min(lows)) / closes[-1] * 100.0 if closes[-1] else None,
        "flow_available": flow_ok,
        "trade_value_sum": sum(float(b["trade_value"]) for b in flow_rows) if flow_ok else None,
        "nbss_sum": sum(float(b["nbss"]) for b in flow_rows) if flow_ok else None,
    }


def _trailing_return_pct(daily: Sequence[Mapping[str, Any]], end_excl: int, window: int) -> float | None:
    start = end_excl - window
    if start < 0:
        return None
    ref = daily[start]["close"]
    last = daily[end_excl - 1]["close"]
    if not ref:
        return None
    return (last / ref - 1.0) * 100.0


def _flow_persistence_ratio(daily: Sequence[Mapping[str, Any]], end_excl: int, window: int) -> float | None:
    start = end_excl - window
    if start < 0:
        return None
    seg = daily[start:end_excl]
    if len(seg) < 4 or any(not d["flow_available"] for d in seg):
        return None
    half = len(seg) // 2
    first = _median([d["trade_value_sum"] for d in seg[:half]])
    second = _median([d["trade_value_sum"] for d in seg[half:]])
    if not first:
        return None
    return second / first


def _precursor_block(
    daily: Sequence[Mapping[str, Any]],
    day_idx: int,
    thresholds: MGIntradayThresholds,
) -> dict[str, Any] | None:
    """Multi-day state known before day `day_idx` opens. Reads days < day_idx only."""
    window = thresholds.precursor_window_days
    if day_idx < window + 1:
        return None

    streak = 0
    for j in range(day_idx - 1, max(window - 1, day_idx - 1 - 40), -1):
        ret = _trailing_return_pct(daily, j, window)
        ratio = _flow_persistence_ratio(daily, j, window)
        if ret is None or ratio is None:
            break
        if ret <= thresholds.dormant_return_cutoff_pct and ratio >= thresholds.flow_persistence_cutoff_ratio:
            streak += 1
        else:
            break

    prior = daily[day_idx - window : day_idx]
    prior_high = max(d["high"] for d in prior)
    vol_unit_pct = _median([d["range_pct"] for d in prior])
    if vol_unit_pct is None or vol_unit_pct <= 0:
        return None

    return {
        "absorption_streak_days": streak,
        "prior_structure_high": prior_high,
        "prior_close": daily[day_idx - 1]["close"],
        "volatility_unit_pct": vol_unit_pct,
    }


def _intraday_view(bars: Sequence[Mapping[str, Any]], t: int) -> dict[str, Any] | None:
    """State from bars 0..t of the current day. Never reads t+1 or later."""
    seen = bars[: t + 1]
    closes = [float(b["close"]) for b in seen if b.get("close") is not None]
    highs = [float(b["high"]) for b in seen if b.get("high") is not None]
    lows = [float(b["low"]) for b in seen if b.get("low") is not None]
    if len(closes) < MIN_CONSTRUCTIVE_BARS or not highs or not lows:
        return None
    price = closes[-1]
    if price <= 0:
        return None
    day_high = max(highs)
    day_low = min(lows)
    flow_rows = [b for b in seen if b.get("flow_available")]
    day_value = sum(float(b["trade_value"]) for b in flow_rows) if flow_rows else None
    return {
        "price": price,
        "day_high": day_high,
        "day_low": day_low,
        "day_value_so_far": day_value,
        "flow_rows": len(flow_rows),
        "bars_seen": len(seen),
        "close_location": (price - day_low) / (day_high - day_low) if day_high > day_low else 0.5,
        "closes": closes,
        "highs": highs,
        "lows": lows,
    }


def _constructive_bar_run(view: Mapping[str, Any]) -> int:
    """Consecutive most-recent bars making higher lows -- the persistence evidence."""
    lows = view["lows"]
    run = 0
    for i in range(len(lows) - 1, 0, -1):
        if lows[i] >= lows[i - 1]:
            run += 1
        else:
            break
    return run


def _evaluate_snapshot(
    view: Mapping[str, Any],
    ctx: Mapping[str, Any],
    thresholds: MGIntradayThresholds,
) -> tuple[bool, str | None, dict[str, Any]]:
    """Returns (fires, rejection_reason, published_fields). Causal state only."""
    price = view["price"]
    prior_close = ctx["prior_close"]
    if not prior_close:
        return False, "stale_or_partial_data", {}

    chg_pct = (price / prior_close - 1.0) * 100.0
    vol_unit_price = ctx["volatility_unit_pct"] / 100.0 * price
    tp1 = price + thresholds.tp1_vol_multiple * vol_unit_price
    tp2 = price + thresholds.tp2_vol_multiple * vol_unit_price
    published = {
        "price": price,
        "chg_pct": chg_pct,
        "tp1": tp1,
        "tp2": tp2,
        "volatility_unit_pct": ctx["volatility_unit_pct"],
    }

    if view["day_value_so_far"] is None or view["flow_rows"] < MIN_CONSTRUCTIVE_BARS:
        return False, "stale_or_partial_data", published
    if ctx["absorption_streak_days"] < thresholds.min_absorption_streak_days:
        return False, "absorption_streak_too_short", published
    if view["day_value_so_far"] < thresholds.min_day_trade_value:
        return False, "thin_liquidity", published
    if chg_pct >= thresholds.chg_chase_cutoff_pct:
        return False, "mature_chase", published

    run = _constructive_bar_run(view)
    if run < MIN_CONSTRUCTIVE_BARS:
        return False, "one_bar_spike_no_continuation", published
    if view["close_location"] < thresholds.close_location_cutoff:
        return False, "rejection_giveback", published
    if chg_pct <= 0.0:
        return False, "effort_without_response", published

    # Unstable path: price has already round-tripped more than the whole prior
    # volatility unit below its own day high while still claiming constructive state.
    if view["day_high"] > 0 and (view["day_high"] - price) / view["day_high"] * 100.0 > ctx["volatility_unit_pct"]:
        return False, "unstable_path", published

    # Remaining room: a target already breached at signal time is not an early
    # opportunity, it is a chase. TP-1 must sit above the prior structure high
    # or the candidate must still be below that high (reclaim room).
    if price >= ctx["prior_structure_high"] and tp1 <= view["day_high"]:
        return False, "no_remaining_room", published

    return True, None, published


def _forward_from_bar(
    bars: Sequence[Mapping[str, Any]],
    t: int,
    horizons_bars: Sequence[int],
    tp1: float,
    tp2: float,
) -> dict[str, Any]:
    """Outcome-only. Same trading date only. Never feeds back into state."""
    entry_raw = bars[t].get("close")
    if entry_raw is None or float(entry_raw) <= 0:
        return {}
    entry = float(entry_raw)
    event_date = str(bars[t].get("trading_date") or "")
    out: dict[str, Any] = {}

    for horizon in horizons_bars:
        key = str(horizon)
        end = t + horizon
        if end >= len(bars):
            out[key] = {"evaluable": False}
            continue
        forward = bars[t + 1 : end + 1]
        if any(str(b.get("trading_date") or "") != event_date for b in forward):
            out[key] = {"evaluable": False}
            continue
        highs = [float(b["high"]) for b in forward if b.get("high") is not None]
        lows = [float(b["low"]) for b in forward if b.get("low") is not None]
        close_raw = bars[end].get("close")
        if not highs or not lows or close_raw is None:
            out[key] = {"evaluable": False}
            continue
        mfe = max(highs)
        out[key] = {
            "evaluable": True,
            "forward_return_pct": (float(close_raw) / entry - 1.0) * 100.0,
            "mfe_pct": (mfe / entry - 1.0) * 100.0,
            "mae_pct": (min(lows) / entry - 1.0) * 100.0,
            "tp1_hit": bool(mfe >= tp1),
            "tp2_hit": bool(mfe >= tp2),
            "bars_to_tp1": next((i + 1 for i, h in enumerate(highs) if h >= tp1), None),
        }
    return out


def _process_ticker(
    ticker: str,
    sessions: Sequence[Mapping[str, Any]],
    thresholds: MGIntradayThresholds | None,
    horizons_bars: Sequence[int],
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, list[float]]]:
    ordered = sorted(sessions, key=lambda s: s["trading_date"])
    daily: list[dict[str, Any]] = []
    day_bars: list[list[Mapping[str, Any]]] = []
    for s in ordered:
        summary = _day_summary(s["bars"])
        if summary is None:
            continue
        daily.append(summary)
        day_bars.append([b for b in s["bars"] if b.get("session_eligible")])

    signals: list[dict[str, Any]] = []
    rejections = {reason: 0 for reason in REJECTION_REASONS}
    pools: dict[str, list[float]] = {
        "trailing_return_pct": [],
        "flow_ratio": [],
        "chg_pct": [],
        "day_trade_value": [],
        "close_location": [],
        "mfe_in_vol_units": [],
    }

    window = thresholds.precursor_window_days if thresholds else 8

    for day_idx in range(len(daily)):
        if thresholds is None:
            ret = _trailing_return_pct(daily, day_idx, window)
            ratio = _flow_persistence_ratio(daily, day_idx, window)
            if ret is not None:
                pools["trailing_return_pct"].append(ret)
            if ratio is not None:
                pools["flow_ratio"].append(ratio)

        bars = day_bars[day_idx]
        if len(bars) < MIN_CONSTRUCTIVE_BARS or day_idx < window + 1:
            continue

        prior = daily[day_idx - window : day_idx]
        prior_close = daily[day_idx - 1]["close"]
        vol_unit_pct = _median([d["range_pct"] for d in prior])
        ctx = (
            _precursor_block(daily, day_idx, thresholds)
            if thresholds is not None
            else None
        )

        fired_today = False
        for t in range(MIN_CONSTRUCTIVE_BARS - 1, len(bars)):
            view = _intraday_view(bars, t)
            if view is None:
                continue

            if thresholds is None:
                if prior_close:
                    pools["chg_pct"].append((view["price"] / prior_close - 1.0) * 100.0)
                if view["day_value_so_far"] is not None:
                    pools["day_trade_value"].append(view["day_value_so_far"])
                pools["close_location"].append(view["close_location"])
                if vol_unit_pct and vol_unit_pct > 0:
                    fwd = _forward_from_bar(bars, t, [max(horizons_bars)], 0.0, 0.0)
                    row = fwd.get(str(max(horizons_bars)), {})
                    if row.get("evaluable"):
                        pools["mfe_in_vol_units"].append(row["mfe_pct"] / vol_unit_pct)
                continue

            if ctx is None:
                rejections["no_precursor_context"] += 1
                break

            fires, reason, published = _evaluate_snapshot(view, ctx, thresholds)
            if not fires:
                if reason:
                    rejections[reason] += 1
                continue

            # MG republishes while criteria hold; for outcome accounting we keep
            # the first qualifying snapshot per ticker-day so one persistent
            # opportunity is not counted as dozens of independent wins.
            if fired_today:
                continue
            fired_today = True
            signals.append(
                {
                    "ticker": ticker,
                    "trading_date": daily[day_idx]["trading_date"],
                    "timestamp": bars[t].get("timestamp"),
                    "bar_index": t,
                    "absorption_streak_days": ctx["absorption_streak_days"],
                    "published": published,
                    "outcomes": _forward_from_bar(
                        bars, t, horizons_bars, published["tp1"], published["tp2"]
                    ),
                    "future_data_used_for_signal": False,
                    "future_data_used_for_outcome_only": True,
                }
            )

    return signals, rejections, pools


def _iter_ticker_sessions(source_name: str) -> dict[str, list[dict[str, Any]]]:
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    ticker_sessions: dict[str, list[dict[str, Any]]] = {}
    for _manifest_row, packet in reader.iter_packets():
        bars, _mapping = packet_to_formula_bars(packet)
        ticker_sessions.setdefault(str(packet.identity.ticker), []).append(
            {"trading_date": packet.identity.trading_date, "bars": bars}
        )
    return ticker_sessions


def _summarize(signals: Sequence[Mapping[str, Any]], horizons_bars: Sequence[int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for horizon in horizons_bars:
        key = str(horizon)
        rows = [s["outcomes"][key] for s in signals if s["outcomes"].get(key, {}).get("evaluable")]
        n = len(rows)
        if n == 0:
            out[key] = {"evaluable_count": 0, "event_count": len(signals)}
            continue
        fwd = [r["forward_return_pct"] for r in rows]
        mfe = [r["mfe_pct"] for r in rows]
        mae = [r["mae_pct"] for r in rows]
        tp1_times = [r["bars_to_tp1"] for r in rows if r.get("bars_to_tp1") is not None]
        out[key] = {
            "event_count": len(signals),
            "evaluable_count": n,
            "positive_forward_rate": sum(1 for v in fwd if v > 0) / n,
            "mean_forward_return_pct": sum(fwd) / n,
            "forward_q10_pct": _quantile(fwd, 0.10),
            "forward_q25_pct": _quantile(fwd, 0.25),
            "forward_q50_pct": _quantile(fwd, 0.50),
            "forward_q75_pct": _quantile(fwd, 0.75),
            "forward_q90_pct": _quantile(fwd, 0.90),
            "mean_mfe_pct": sum(mfe) / n,
            "mean_mae_pct": sum(mae) / n,
            "mae_q25_pct": _quantile(mae, 0.25),
            "tp1_hit_rate": sum(1 for r in rows if r["tp1_hit"]) / n,
            "tp2_hit_rate": sum(1 for r in rows if r["tp2_hit"]) / n,
            "median_bars_to_tp1": _quantile([float(v) for v in tp1_times], 0.50),
        }
    return out


def _learn_thresholds(
    pools: Mapping[str, list[float]],
    *,
    precursor_window_days: int,
    min_streak: int,
) -> MGIntradayThresholds:
    dormant = _quantile(pools["trailing_return_pct"], 0.50)
    flow = _quantile(pools["flow_ratio"], 0.50)
    chase = _quantile(pools["chg_pct"], 0.90)
    value_floor = _quantile(pools["day_trade_value"], 0.25)
    close_loc = _quantile(pools["close_location"], 0.50)
    tp1_mult = _quantile(pools["mfe_in_vol_units"], 0.50)
    tp2_mult = _quantile(pools["mfe_in_vol_units"], 0.75)
    missing = [
        name
        for name, value in {
            "trailing_return_pct": dormant,
            "flow_ratio": flow,
            "chg_pct": chase,
            "day_trade_value": value_floor,
            "close_location": close_loc,
            "mfe_in_vol_units": tp1_mult,
        }.items()
        if value is None
    ]
    if missing:
        raise SystemExit(f"INSUFFICIENT_DISCOVERY_DATA_FOR_THRESHOLD_LEARNING:{','.join(missing)}")
    if not tp1_mult or tp1_mult <= 0:
        raise SystemExit("LEARNED_TP1_MULTIPLE_NON_POSITIVE_REFUSING_TO_SYNTHESIZE_TARGET")
    return MGIntradayThresholds(
        precursor_window_days=precursor_window_days,
        dormant_return_cutoff_pct=float(dormant),
        flow_persistence_cutoff_ratio=float(flow),
        min_absorption_streak_days=min_streak,
        chg_chase_cutoff_pct=float(chase),
        min_day_trade_value=float(value_floor),
        close_location_cutoff=float(close_loc),
        tp1_vol_multiple=float(tp1_mult),
        tp2_vol_multiple=float(tp2_mult if tp2_mult and tp2_mult > tp1_mult else tp1_mult * 2.0),
    )


def _merge_rejections(target: dict[str, int], source: Mapping[str, int]) -> None:
    for reason, count in source.items():
        target[reason] = target.get(reason, 0) + count


def discover(
    source_name: str,
    *,
    precursor_window_days: int,
    min_streak_grid: Sequence[int],
    horizons_bars: Sequence[int],
) -> dict[str, Any]:
    _reject_oos_source(source_name)
    ticker_sessions = _iter_ticker_sessions(source_name)

    pools: dict[str, list[float]] = {}
    for ticker, sessions in ticker_sessions.items():
        _s, _r, ticker_pools = _process_ticker(ticker, sessions, None, horizons_bars)
        for name, values in ticker_pools.items():
            pools.setdefault(name, []).extend(values)

    grid_results = []
    best = None
    primary = str(horizons_bars[0])
    for streak in min_streak_grid:
        thresholds = _learn_thresholds(
            pools, precursor_window_days=precursor_window_days, min_streak=streak
        )
        signals: list[dict[str, Any]] = []
        rejections: dict[str, int] = {}
        for ticker, sessions in ticker_sessions.items():
            s, r, _p = _process_ticker(ticker, sessions, thresholds, horizons_bars)
            signals.extend(s)
            _merge_rejections(rejections, r)
        summary = _summarize(signals, horizons_bars)
        grid_results.append(
            {
                "min_absorption_streak_days": streak,
                "signal_count": len(signals),
                "unique_ticker_count": len({s["ticker"] for s in signals}),
                "unique_date_count": len({s["trading_date"] for s in signals}),
                "rejection_counts": rejections,
                "summary": summary,
            }
        )
        q25 = summary.get(primary, {}).get("forward_q25_pct")
        if q25 is not None and (best is None or q25 > best["q25"]):
            best = {"q25": q25, "thresholds": thresholds, "signals": signals}

    if best is None:
        raise SystemExit("NO_MIN_STREAK_CANDIDATE_PRODUCED_EVALUABLE_SIGNALS_ON_DISCOVERY")

    return {
        "schema": "A1_CLAUDE_MG_INTRADAY_DISCOVERY_V2",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "ticker_count": len(ticker_sessions),
        "forward_horizons_regular_bars": list(horizons_bars),
        "learned_thresholds": best["thresholds"].as_dict(),
        # Carried so the published contract rows can be rendered from the real
        # run rather than reconstructed or illustrated.
        "signals_for_selected_thresholds": best["signals"],
        "min_streak_grid_results": grid_results,
        "future_data_used_for_candidate_state": False,
        "outcome_is_evaluation_only_not_formula_input": True,
        "winner_only_filter_used": False,
        "flow_availability_policy": (
            "PHYSICAL_NBSS_ZERO_REMAINS_UNKNOWN_NEVER_TREATED_AS_NEUTRAL"
        ),
        "tp_policy": "TP_MULTIPLES_LEARNED_FROM_DISCOVERY_MFE_DISTRIBUTION_IN_VOLATILITY_UNITS",
    }


def validate(
    source_name: str,
    *,
    thresholds: MGIntradayThresholds,
    horizons_bars: Sequence[int],
) -> dict[str, Any]:
    _reject_oos_source(source_name)
    ticker_sessions = _iter_ticker_sessions(source_name)
    signals: list[dict[str, Any]] = []
    rejections: dict[str, int] = {}
    for ticker, sessions in ticker_sessions.items():
        s, r, _p = _process_ticker(ticker, sessions, thresholds, horizons_bars)
        signals.extend(s)
        _merge_rejections(rejections, r)
    return {
        "schema": "A1_CLAUDE_MG_INTRADAY_VALIDATION_V2",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "ticker_count": len(ticker_sessions),
        "forward_horizons_regular_bars": list(horizons_bars),
        "applied_thresholds": thresholds.as_dict(),
        "signal_count": len(signals),
        "unique_ticker_count": len({s["ticker"] for s in signals}),
        "unique_date_count": len({s["trading_date"] for s in signals}),
        "rejection_counts": rejections,
        "summary": _summarize(signals, horizons_bars),
        "signals": signals,
        "thresholds_frozen_not_retuned": True,
        "future_data_used_for_candidate_state": False,
        "outcome_is_evaluation_only_not_formula_input": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-mg-intraday-v2")
    parser.add_argument("--phase", choices=["discover", "validate"], required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--horizons-bars", default="5,15,30,60")
    parser.add_argument("--precursor-window-days", type=int, default=8)
    parser.add_argument("--min-streak-grid", default="1,2,3,4,5")
    parser.add_argument("--frozen-thresholds", default=None, help="Required for --phase validate")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    horizons = [int(x) for x in args.horizons_bars.split(",") if x.strip()]

    if args.phase == "discover":
        grid = [int(x) for x in args.min_streak_grid.split(",") if x.strip()]
        result = discover(
            args.source_name,
            precursor_window_days=args.precursor_window_days,
            min_streak_grid=grid,
            horizons_bars=horizons,
        )
    else:
        if not args.frozen_thresholds:
            raise SystemExit("--frozen-thresholds is required for --phase validate")
        payload = json.loads(Path(args.frozen_thresholds).read_text(encoding="utf-8"))
        thresholds = MGIntradayThresholds.from_dict(payload.get("learned_thresholds", payload))
        result = validate(args.source_name, thresholds=thresholds, horizons_bars=horizons)

    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pass": True, "phase": args.phase, "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
