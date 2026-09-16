"""Claude-owned MG research: owner-posed hypotheses on open-extremes and rung escalation.

RESEARCH_ONLY. Not canonical, not live-eligible. Lane: `research/claude-mg-discovery`.

--------------------------------------------------------------------------
THE THREE OWNER QUESTIONS THIS MODULE ANSWERS WITH MEASURED DATA
--------------------------------------------------------------------------
Q-A  Is `Open == Low` reliably followed by an up move?
Q-B  Is `Open == High` reliably followed by a down move?
Q-C  Does strength escalate in rungs -- if price pushes through +3.5% does it
     confirm to +5%, and from +5% through +5.7% does it confirm to +12%, and
     so on?

These are answered as PROBABILITIES AGAINST THE UNCONDITIONAL BASELINE, never
as yes/no. A pattern that resolves up 55% of the time is worthless if the whole
universe resolves up 54% of the time, so every conditional number below is
reported beside the same statistic computed on all eligible ticker-days, plus
its lift.

--------------------------------------------------------------------------
CAUSAL VS HINDSIGHT -- THE DISTINCTION THAT DECIDES IF THIS CAN BE A FORMULA
--------------------------------------------------------------------------
`Open == Low` has two meanings and only one of them can drive a signal.

  HINDSIGHT form: the open equals the day's FINAL low. Known only after the
  close. This is a research label. It cannot be an executable input, and the
  Master's causality contract forbids backdating it into a decision state.

  CAUSAL form: at snapshot bar t, price has not traded below the open at any
  point up to t (`low_so_far == open`). This IS knowable live at every 5-minute
  publication slot, so this is the form a formula could actually use.

Both are measured and reported separately. Reading the hindsight number as if
it were tradable is the single most likely way to fool ourselves here, so the
output labels them explicitly.

--------------------------------------------------------------------------
THE DEGENERATE-DAY TRAP
--------------------------------------------------------------------------
An untraded or barely-traded ticker-day where open == high == low == close
satisfies `Open == Low` trivially. It is not strength, it is absence of
trading. Such days are counted separately and excluded from the conditional
statistics; their count is reported so the exclusion is visible rather than
silent.

--------------------------------------------------------------------------
WHY THE LADDER MATTERS BEYOND ITS OWN QUESTION
--------------------------------------------------------------------------
If `P(reach next rung | reached this rung)` is materially above the
unconditional base rate, then the rungs are behavioral levels the market
actually respects, and TP-1/TP-2 can be derived from them -- targets born from
observed market structure, which is what Master section 20A.6 requires. The
prior candidate's targets came from a quantile of an undifferentiated bar
population and were consequently trivial; this is the principled replacement,
if the data supports it.

All rung arithmetic is against the PREVIOUS DAY'S CLOSE, matching the CHG%
the MG output contract publishes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..pattern_discovery.source_reader import GovernedSourceReader
from ..google_drive import build_drive_api
from .formula_replay import packet_to_formula_bars

RESERVED_OOS_SOURCE_TOKENS = ("mar", "maret")

DEFAULT_UP_LADDER = "1,2,3,3.5,4,5,5.7,7,10,12,15,20,25"
DEFAULT_DOWN_LADDER = "1,2,3,3.5,4,5,5.7,7,10,12,15,20,25"


def _reject_oos_source(source_name: str) -> None:
    lowered = source_name.casefold()
    if any(token in lowered for token in RESERVED_OOS_SOURCE_TOKENS):
        raise SystemExit(
            f"REFUSING_TO_TOUCH_RESERVED_OOS_SOURCE:{source_name}:"
            "March 2025 remains untouched OOS per CLAUDE.md."
        )


@dataclass
class Counter:
    """Accumulates one conditional cell without retaining per-event rows."""

    n: int = 0
    close_above_open: int = 0
    close_above_prev: int = 0
    day_returns: list[float] | None = None

    def __post_init__(self) -> None:
        if self.day_returns is None:
            self.day_returns = []

    def add(self, *, close_gt_open: bool, close_gt_prev: bool, day_return_pct: float) -> None:
        self.n += 1
        self.close_above_open += int(close_gt_open)
        self.close_above_prev += int(close_gt_prev)
        self.day_returns.append(day_return_pct)

    def as_dict(self) -> dict[str, Any]:
        if self.n == 0:
            return {"n": 0}
        returns = sorted(self.day_returns or [])

        def q(p: float) -> float:
            idx = min(len(returns) - 1, max(0, int(round(p * (len(returns) - 1)))))
            return returns[idx]

        return {
            "n": self.n,
            "p_close_above_open": self.close_above_open / self.n,
            "p_close_above_prev_close": self.close_above_prev / self.n,
            "mean_day_return_pct": sum(returns) / len(returns),
            "q10_day_return_pct": q(0.10),
            "q25_day_return_pct": q(0.25),
            "median_day_return_pct": q(0.50),
            "q75_day_return_pct": q(0.75),
            "q90_day_return_pct": q(0.90),
        }


def _lift(conditional: Mapping[str, Any], baseline: Mapping[str, Any], key: str) -> float | None:
    """Conditional minus baseline, in percentage points. The number that matters."""
    if conditional.get("n", 0) == 0 or baseline.get("n", 0) == 0:
        return None
    if key not in conditional or key not in baseline:
        return None
    return (conditional[key] - baseline[key]) * 100.0


def _day_view(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    eligible = [b for b in bars if b.get("session_eligible")]
    if not eligible:
        return None
    opens = [b for b in eligible if b.get("open") is not None]
    closes = [float(b["close"]) for b in eligible if b.get("close") is not None]
    highs = [float(b["high"]) for b in eligible if b.get("high") is not None]
    lows = [float(b["low"]) for b in eligible if b.get("low") is not None]
    if not opens or not closes or not highs or not lows:
        return None
    day_open = float(opens[0]["open"])
    if day_open <= 0:
        return None
    return {
        "trading_date": eligible[0]["trading_date"],
        "open": day_open,
        "high": max(highs),
        "low": min(lows),
        "close": closes[-1],
        "bars": eligible,
    }


def _first_touch_bar(bars: Sequence[Mapping[str, Any]], level: float, *, upward: bool) -> int | None:
    for i, bar in enumerate(bars):
        probe = bar.get("high") if upward else bar.get("low")
        if probe is None:
            continue
        if (upward and float(probe) >= level) or ((not upward) and float(probe) <= level):
            return i
    return None


def _cross_was_strong(bars: Sequence[Mapping[str, Any]], idx: int, *, upward: bool) -> bool:
    """Strength judged ONLY at the crossing bar -- no forward bars consulted."""
    bar = bars[idx]
    high, low, close, open_ = bar.get("high"), bar.get("low"), bar.get("close"), bar.get("open")
    if None in (high, low, close):
        return False
    high, low, close = float(high), float(low), float(close)
    if high <= low:
        return False
    location = (close - low) / (high - low)
    directional = location >= 0.5 if upward else location <= 0.5
    if open_ is not None:
        directional = directional and (close >= float(open_) if upward else close <= float(open_))

    prior = [
        float(b["trade_value"])
        for b in bars[max(0, idx - 5) : idx]
        if b.get("flow_available") and b.get("trade_value") is not None
    ]
    this_value = float(bar["trade_value"]) if bar.get("flow_available") and bar.get("trade_value") is not None else None
    if prior and this_value is not None:
        expansion = this_value > statistics.median(prior)
    else:
        expansion = True  # flow unproven -> strength decided on price alone, never on a fabricated zero
    return bool(directional and expansion)


def _blank_rung() -> dict[str, Any]:
    return {
        "reached": 0,
        "reached_and_next": 0,
        "reached_strong": 0,
        "reached_strong_and_next": 0,
        "closed_at_or_above_rung": 0,
        "bars_to_next": [],
    }


def analyse(
    source_name: str,
    *,
    up_ladder: Sequence[float],
    down_ladder: Sequence[float],
) -> dict[str, Any]:
    _reject_oos_source(source_name)
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)

    per_ticker: dict[str, list[dict[str, Any]]] = {}
    for _row, packet in reader.iter_packets():
        bars, _mapping = packet_to_formula_bars(packet)
        view = _day_view(bars)
        if view is None:
            continue
        per_ticker.setdefault(str(packet.identity.ticker), []).append(view)

    baseline = Counter()
    open_is_low = Counter()
    open_is_high = Counter()
    open_is_both = Counter()

    degenerate_flat_days = 0
    total_days = 0
    evaluated_days = 0

    causal_open_low = {"snapshots": 0, "close_above_snapshot": 0}
    causal_open_high = {"snapshots": 0, "close_below_snapshot": 0}

    up_rungs = {str(r): _blank_rung() for r in up_ladder}
    down_rungs = {str(r): _blank_rung() for r in down_ladder}

    for _ticker, days in per_ticker.items():
        days.sort(key=lambda d: d["trading_date"])
        for i in range(1, len(days)):
            day = days[i]
            prev_close = days[i - 1]["close"]
            total_days += 1
            if not prev_close or prev_close <= 0:
                continue

            if day["high"] <= day["low"]:
                degenerate_flat_days += 1
                continue

            evaluated_days += 1
            day_return_pct = (day["close"] / prev_close - 1.0) * 100.0
            close_gt_open = day["close"] > day["open"]
            close_gt_prev = day["close"] > prev_close
            baseline.add(
                close_gt_open=close_gt_open,
                close_gt_prev=close_gt_prev,
                day_return_pct=day_return_pct,
            )

            is_low = day["open"] <= day["low"]
            is_high = day["open"] >= day["high"]
            if is_low:
                open_is_low.add(
                    close_gt_open=close_gt_open, close_gt_prev=close_gt_prev, day_return_pct=day_return_pct
                )
            if is_high:
                open_is_high.add(
                    close_gt_open=close_gt_open, close_gt_prev=close_gt_prev, day_return_pct=day_return_pct
                )
            if is_low and is_high:
                open_is_both.add(
                    close_gt_open=close_gt_open, close_gt_prev=close_gt_prev, day_return_pct=day_return_pct
                )

            bars = day["bars"]

            # Causal form: state known live at each snapshot, outcome is the
            # day's own close. Evaluation only -- never fed back as a feature.
            low_so_far = None
            high_so_far = None
            for t, bar in enumerate(bars):
                bar_low = bar.get("low")
                bar_high = bar.get("high")
                bar_close = bar.get("close")
                if bar_low is not None:
                    low_so_far = float(bar_low) if low_so_far is None else min(low_so_far, float(bar_low))
                if bar_high is not None:
                    high_so_far = float(bar_high) if high_so_far is None else max(high_so_far, float(bar_high))
                if bar_close is None or t == len(bars) - 1:
                    continue
                price = float(bar_close)
                if low_so_far is not None and low_so_far >= day["open"]:
                    causal_open_low["snapshots"] += 1
                    causal_open_low["close_above_snapshot"] += int(day["close"] > price)
                if high_so_far is not None and high_so_far <= day["open"]:
                    causal_open_high["snapshots"] += 1
                    causal_open_high["close_below_snapshot"] += int(day["close"] < price)

            # Rung escalation, upward then downward.
            for ladder, rungs, upward in ((up_ladder, up_rungs, True), (down_ladder, down_rungs, False)):
                touches: dict[str, int | None] = {}
                for rung in ladder:
                    level = prev_close * (1.0 + (rung if upward else -rung) / 100.0)
                    touches[str(rung)] = _first_touch_bar(bars, level, upward=upward)
                for k, rung in enumerate(ladder):
                    key = str(rung)
                    idx = touches[key]
                    if idx is None:
                        continue
                    cell = rungs[key]
                    cell["reached"] += 1
                    strong = _cross_was_strong(bars, idx, upward=upward)
                    cell["reached_strong"] += int(strong)
                    level = prev_close * (1.0 + (rung if upward else -rung) / 100.0)
                    held = day["close"] >= level if upward else day["close"] <= level
                    cell["closed_at_or_above_rung"] += int(held)
                    if k + 1 >= len(ladder):
                        continue
                    next_idx = touches[str(ladder[k + 1])]
                    if next_idx is not None and next_idx >= idx:
                        cell["reached_and_next"] += 1
                        cell["bars_to_next"].append(float(next_idx - idx))
                        if strong:
                            cell["reached_strong_and_next"] += 1

    def finalize_rungs(rungs: Mapping[str, Mapping[str, Any]], ladder: Sequence[float]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, rung in enumerate(ladder):
            key = str(rung)
            cell = rungs[key]
            reached = cell["reached"]
            strong = cell["reached_strong"]
            gaps = sorted(cell["bars_to_next"])
            out[key] = {
                "next_rung": str(ladder[k + 1]) if k + 1 < len(ladder) else None,
                "ticker_days_reached": reached,
                "p_reach_next_rung_given_reached": (cell["reached_and_next"] / reached) if reached else None,
                "ticker_days_reached_with_strong_cross": strong,
                "p_reach_next_rung_given_strong_cross": (
                    cell["reached_strong_and_next"] / strong if strong else None
                ),
                "p_closed_at_or_beyond_rung_given_reached": (
                    cell["closed_at_or_above_rung"] / reached if reached else None
                ),
                "median_bars_to_next_rung": (gaps[len(gaps) // 2] if gaps else None),
            }
        return out

    base = baseline.as_dict()
    low = open_is_low.as_dict()
    high = open_is_high.as_dict()

    return {
        "schema": "A1_CLAUDE_OPEN_EXTREME_LADDER_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "ticker_count": len(per_ticker),
        "ticker_days_seen": total_days,
        "ticker_days_evaluated": evaluated_days,
        "degenerate_flat_days_excluded": degenerate_flat_days,
        "rung_basis": "PREVIOUS_DAY_CLOSE",
        "winner_only_filter_used": False,
        "outcome_is_evaluation_only_not_formula_input": True,
        "unconditional_baseline": base,
        "hindsight_open_equals_low": {
            "note": "HINDSIGHT LABEL -- open equals the day's FINAL low. Not executable.",
            **low,
            "lift_p_close_above_open_pp": _lift(low, base, "p_close_above_open"),
            "lift_p_close_above_prev_close_pp": _lift(low, base, "p_close_above_prev_close"),
        },
        "hindsight_open_equals_high": {
            "note": "HINDSIGHT LABEL -- open equals the day's FINAL high. Not executable.",
            **high,
            "lift_p_close_above_open_pp": _lift(high, base, "p_close_above_open"),
            "lift_p_close_above_prev_close_pp": _lift(high, base, "p_close_above_prev_close"),
        },
        "hindsight_open_equals_low_and_high": {
            "note": "Non-degenerate days that still opened at both extremes.",
            **open_is_both.as_dict(),
        },
        "causal_open_is_low_so_far": {
            "note": "EXECUTABLE FORM -- at this snapshot price has never traded below the open.",
            "snapshots": causal_open_low["snapshots"],
            "p_close_above_snapshot_price": (
                causal_open_low["close_above_snapshot"] / causal_open_low["snapshots"]
                if causal_open_low["snapshots"]
                else None
            ),
        },
        "causal_open_is_high_so_far": {
            "note": "EXECUTABLE FORM -- at this snapshot price has never traded above the open.",
            "snapshots": causal_open_high["snapshots"],
            "p_close_below_snapshot_price": (
                causal_open_high["close_below_snapshot"] / causal_open_high["snapshots"]
                if causal_open_high["snapshots"]
                else None
            ),
        },
        "up_rung_escalation": finalize_rungs(up_rungs, up_ladder),
        "down_rung_escalation": finalize_rungs(down_rungs, down_ladder),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-open-extreme-ladder-v1")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--up-ladder", default=DEFAULT_UP_LADDER)
    parser.add_argument("--down-ladder", default=DEFAULT_DOWN_LADDER)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    up = [float(x) for x in args.up_ladder.split(",") if x.strip()]
    down = [float(x) for x in args.down_ladder.split(",") if x.strip()]
    result = analyse(args.source_name, up_ladder=up, down_ladder=down)

    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pass": True, "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
