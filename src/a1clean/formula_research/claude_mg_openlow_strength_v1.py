"""Open=Low scout + ignition, with rung-based targets and a 10%-strength study.

RESEARCH_ONLY. Lane: `research/claude-mg-discovery`.

--------------------------------------------------------------------------
WHY THIS EXISTS AFTER THE OPEN=LOW NULL RESULT
--------------------------------------------------------------------------
Ledger Entry 008 measured `Open == Low` ON ITS OWN and found no tradable edge:
the causal form returned `P(close > price now) = 34.33%` against a 35.03% base
rate. That result stands, and it is NOT what this module re-tests.

The owner's construction is different in a way that matters: `Open == Low` is a
**scout**, and a signal is only raised once the ticker is ALSO already up by a
meaningful amount on the day. `scout AND chg >= X` is a different conditional
from `scout` alone, and nothing measured so far speaks to it. A null result for
a condition is not a null result for that condition combined with another.

--------------------------------------------------------------------------
THE TARGET PROBLEM THIS FIXES
--------------------------------------------------------------------------
Entry 006's targets came from a quantile of the undifferentiated bar population
and were consequently trivial -- one ticker published with TP-1 equal to its own
entry price. Here TP-1/TP-2 are the **next rungs up the measured ladder**, using
the transition table from Entry 008 (run 35097581002). Targets are therefore
levels the market was observed to respect, which is what Master §20A.6 requires.

--------------------------------------------------------------------------
THE 10% QUESTION
--------------------------------------------------------------------------
The owner wants the tickers that are genuinely strong enough to carry to +10%.
That is treated here as its own labelled outcome, not as a target that happens
to be far away. For every signal the module records whether the day actually
reached +10%, then contrasts the reached-10% group against the rest on features
that were observable AT SIGNAL TIME ONLY -- change at signal, bar index, value
expansion, close location, prior-day range. The contrast is what could later
justify a stricter gate; the module does not assume one exists.

--------------------------------------------------------------------------
CAUSALITY
--------------------------------------------------------------------------
Scout and ignition read only bars 0..t of the day plus the previous day's close.
Everything after t -- target hits, the 10% label, the final outcome -- is
evaluation only, clipped to the same trading date, and never re-enters a gate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..pattern_discovery.source_reader import GovernedSourceReader
from ..google_drive import build_drive_api
from .formula_replay import packet_to_formula_bars

RESERVED_OOS_SOURCE_TOKENS = ("mar", "maret")

# Measured ladder from Entry 008 (run 35097581002). Targets are levels the
# market was observed to respect, not chosen round numbers.
DEFAULT_RUNGS = (3.5, 5.0, 5.7, 7.0, 10.0, 12.0, 15.0, 20.0, 25.0)

MIN_BARS = 2


def _reject_oos_source(source_name: str) -> None:
    lowered = source_name.casefold()
    if any(token in lowered for token in RESERVED_OOS_SOURCE_TOKENS):
        raise SystemExit(
            f"REFUSING_TO_TOUCH_RESERVED_OOS_SOURCE:{source_name}:"
            "March 2025 remains untouched OOS per CLAUDE.md."
        )


def _next_rungs(chg_pct: float, rungs: Sequence[float]) -> tuple[float | None, float | None]:
    """The next two ladder rungs strictly above the current change."""
    above = [r for r in rungs if r > chg_pct]
    if not above:
        return None, None
    if len(above) == 1:
        return above[0], None
    return above[0], above[1]


def _day_frame(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    eligible = [b for b in bars if b.get("session_eligible")]
    if len(eligible) < MIN_BARS:
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
        "trading_date": str(eligible[0]["trading_date"]),
        "open": day_open,
        "high": max(highs),
        "low": min(lows),
        "close": closes[-1],
        "range_pct": (max(highs) - min(lows)) / closes[-1] * 100.0 if closes[-1] else None,
        "bars": eligible,
    }


def _slot_hhmm(timestamp: str | None, minutes: int = 5) -> str:
    """Telegram Sub-Sub Master section 4/7: for periodic snapshot output the
    displayed HH:MM is the PUBLICATION SLOT identity, not the bar minute. A
    signal may become true between slots; the next snapshot publishes it."""
    raw = _hhmm(timestamp)
    if raw == "??:??":
        return raw
    hour, minute = raw.split(":")
    return f"{hour}:{(int(minute) // minutes) * minutes:02d}"


def _hhmm(timestamp: str | None) -> str:
    if not timestamp or " " not in timestamp:
        return "??:??"
    time_part = timestamp.split(" ", 1)[1]
    pieces = time_part.split(":")
    return f"{pieces[0]}:{pieces[1]}" if len(pieces) >= 2 else "??:??"


def _signal_features(
    bars: Sequence[Mapping[str, Any]], t: int, prior_range_pct: float | None
) -> dict[str, Any]:
    """Everything here is observable at bar t. No forward bars are read."""
    seen = bars[: t + 1]
    bar = bars[t]
    highs = [float(b["high"]) for b in seen if b.get("high") is not None]
    lows = [float(b["low"]) for b in seen if b.get("low") is not None]
    close = float(bar["close"])
    day_high, day_low = max(highs), min(lows)

    prior_values = [
        float(b["trade_value"])
        for b in bars[max(0, t - 5) : t]
        if b.get("flow_available") and b.get("trade_value") is not None
    ]
    this_value = (
        float(bar["trade_value"])
        if bar.get("flow_available") and bar.get("trade_value") is not None
        else None
    )
    expansion = None
    if prior_values and this_value is not None:
        median_prior = statistics.median(prior_values)
        expansion = this_value / median_prior if median_prior else None

    return {
        "bar_index": t,
        "value_expansion": expansion,
        "close_location": (close - day_low) / (day_high - day_low) if day_high > day_low else 0.5,
        "day_range_so_far_pct": (day_high - day_low) / close * 100.0 if close else None,
        "prior_day_range_pct": prior_range_pct,
    }


def _mean(values: Sequence[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def _quantile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank quantile. Small samples must not be smoothed into a number
    the data never produced."""
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    idx = int(round(q * (len(clean) - 1)))
    return clean[idx]


def _forward_path(entry_price: float, forward: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """What the price actually did after the signal, measured from the signal price.

    A rung result answers only "was the target touched". It cannot say whether a
    signal that missed its target drifted sideways or lost money, and the owner's
    question is exactly that. Four numbers answer it:

      mfe_pct             best price reached after the signal
      mae_pct             worst price reached after the signal
      mae_before_peak_pct worst drawdown endured BEFORE that best price, i.e. what
                          a holder had to sit through to see the good outcome
      eod_pct             last close of the same day against the signal price

    All are same-date evaluation of bars strictly after the signal bar, used as
    outcome labels only; none of them is readable at signal time.
    """
    run_min = entry_price
    best = entry_price
    mae_before_peak = 0.0
    last_close = entry_price
    for bar in forward:
        low = bar.get("low")
        if low is not None:
            run_min = min(run_min, float(low))
        high = bar.get("high")
        if high is not None and float(high) > best:
            best = float(high)
            mae_before_peak = (run_min / entry_price - 1.0) * 100.0
        close = bar.get("close")
        if close is not None:
            last_close = float(close)
    return {
        "mfe_pct": (best / entry_price - 1.0) * 100.0,
        "mae_pct": (run_min / entry_price - 1.0) * 100.0,
        "mae_before_peak_pct": mae_before_peak,
        "eod_pct": (last_close / entry_price - 1.0) * 100.0,
    }


def analyse(
    source_name: str,
    *,
    min_chg_pct: float,
    rungs: Sequence[float],
    strength_target_pct: float,
    max_bar_index: int | None = None,
    min_prior_day_range_pct: float | None = None,
) -> dict[str, Any]:
    _reject_oos_source(source_name)
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)

    per_ticker: dict[str, list[dict[str, Any]]] = {}
    for _row, packet in reader.iter_packets():
        bars, _mapping = packet_to_formula_bars(packet)
        frame = _day_frame(bars)
        if frame is None:
            continue
        per_ticker.setdefault(str(packet.identity.ticker), []).append(frame)

    by_date: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"scout": 0, "signals": [], "degenerate": 0}
    )

    for _ticker, days in per_ticker.items():
        days.sort(key=lambda d: d["trading_date"])
        for i in range(1, len(days)):
            day = days[i]
            prev_close = days[i - 1]["close"]
            date = day["trading_date"]
            if not prev_close or prev_close <= 0:
                continue
            if day["high"] <= day["low"]:
                by_date[date]["degenerate"] += 1
                continue

            bars = day["bars"]
            prior_range = days[i - 1]["range_pct"]
            low_so_far = None
            scouted = False
            fired = False

            for t, bar in enumerate(bars):
                bar_low = bar.get("low")
                if bar_low is not None:
                    low_so_far = float(bar_low) if low_so_far is None else min(low_so_far, float(bar_low))
                if bar.get("close") is None or low_so_far is None or t < MIN_BARS - 1:
                    continue

                # SCOUT: price has never traded below the day's open up to here.
                if low_so_far < day["open"]:
                    continue
                if not scouted:
                    scouted = True
                    by_date[date]["scout"] += 1
                if fired:
                    continue

                price = float(bar["close"])
                chg = (price / prev_close - 1.0) * 100.0
                if chg < min_chg_pct:
                    continue
                # Gates derived from the Entry 011 contrast: the group that
                # carried past the strength target fired earlier in the day and
                # was already volatile the day before.
                if max_bar_index is not None and t > max_bar_index:
                    continue
                if min_prior_day_range_pct is not None and (
                    prior_range is None or prior_range < min_prior_day_range_pct
                ):
                    continue

                tp1, tp2 = _next_rungs(chg, rungs)
                if tp1 is None:
                    continue

                fired = True
                tp1_price = prev_close * (1.0 + tp1 / 100.0)
                tp2_price = prev_close * (1.0 + tp2 / 100.0) if tp2 is not None else None

                # Evaluation only, same date, strictly after the signal bar.
                forward = bars[t + 1 :]
                fwd_highs = [float(b["high"]) for b in forward if b.get("high") is not None]
                max_after = max(fwd_highs) if fwd_highs else price
                max_chg_after = (max_after / prev_close - 1.0) * 100.0
                path = _forward_path(price, forward)

                hit_tp1 = max_after >= tp1_price
                hit_tp2 = bool(tp2_price is not None and max_after >= tp2_price)
                reached_strength = max_chg_after >= strength_target_pct

                by_date[date]["signals"].append(
                    {
                        "slot": _slot_hhmm(bar.get("timestamp")),
                        "first_detectable_time": _hhmm(bar.get("timestamp")),
                        "ticker": _ticker,
                        "price": price,
                        "chg_pct": chg,
                        "tp1_pct": tp1,
                        "tp2_pct": tp2,
                        "tp1_price": tp1_price,
                        "tp2_price": tp2_price,
                        "result": "TP2" if hit_tp2 else ("TP1" if hit_tp1 else "FAIL"),
                        "max_chg_after_pct": max_chg_after,
                        # Downside, measured from the SIGNAL PRICE -- the price a
                        # reader of this feed would actually be looking at. Without
                        # these, "FAIL" says only that a rung went untouched and says
                        # nothing about whether the signal lost money.
                        "mfe_pct": path["mfe_pct"],
                        "mae_pct": path["mae_pct"],
                        "mae_before_peak_pct": path["mae_before_peak_pct"],
                        "eod_pct": path["eod_pct"],
                        "eod_positive": path["eod_pct"] > 0.0,
                        f"reached_{int(strength_target_pct)}pct": reached_strength,
                        "features": _signal_features(bars, t, prior_range),
                        "future_data_used_for_signal": False,
                    }
                )

    days_out = []
    all_signals: list[Mapping[str, Any]] = []
    for date in sorted(by_date):
        entry = by_date[date]
        signals = sorted(entry["signals"], key=lambda s: (s["slot"], s["ticker"]))
        all_signals.extend(signals)
        days_out.append(
            {
                "date": date,
                "scout_count": entry["scout"],
                "signal_count": len(signals),
                "tp1_count": sum(1 for s in signals if s["result"] in ("TP1", "TP2")),
                "tp2_count": sum(1 for s in signals if s["result"] == "TP2"),
                "strength_count": sum(
                    1 for s in signals if s[f"reached_{int(strength_target_pct)}pct"]
                ),
                "degenerate_excluded": entry["degenerate"],
                "signals": signals,
            }
        )

    key = f"reached_{int(strength_target_pct)}pct"
    strong = [s for s in all_signals if s[key]]
    weak = [s for s in all_signals if not s[key]]

    def contrast(group: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not group:
            return {"n": 0}
        return {
            "n": len(group),
            "mean_chg_at_signal_pct": _mean([s["chg_pct"] for s in group]),
            "mean_bar_index": _mean([s["features"]["bar_index"] for s in group]),
            "mean_value_expansion": _mean([s["features"]["value_expansion"] for s in group]),
            "mean_close_location": _mean([s["features"]["close_location"] for s in group]),
            "mean_day_range_so_far_pct": _mean([s["features"]["day_range_so_far_pct"] for s in group]),
            "mean_prior_day_range_pct": _mean([s["features"]["prior_day_range_pct"] for s in group]),
        }

    def outcome_block(group: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Was it minus? Answered per group, not asserted."""
        if not group:
            return {"n": 0}
        eod = [s["eod_pct"] for s in group]
        mae = [s["mae_pct"] for s in group]
        return {
            "n": len(group),
            "eod_positive": sum(1 for v in eod if v > 0.0),
            "eod_flat": sum(1 for v in eod if v == 0.0),
            "eod_negative": sum(1 for v in eod if v < 0.0),
            "p_eod_positive": sum(1 for v in eod if v > 0.0) / len(eod),
            "eod_q10_pct": _quantile(eod, 0.10),
            "eod_q25_pct": _quantile(eod, 0.25),
            "eod_median_pct": _quantile(eod, 0.50),
            "eod_q75_pct": _quantile(eod, 0.75),
            "eod_q90_pct": _quantile(eod, 0.90),
            "eod_mean_pct": _mean(eod),
            "mae_median_pct": _quantile(mae, 0.50),
            "mae_q10_pct": _quantile(mae, 0.10),
            "mae_before_peak_median_pct": _quantile(
                [s["mae_before_peak_pct"] for s in group], 0.50
            ),
            "mfe_median_pct": _quantile([s["mfe_pct"] for s in group], 0.50),
        }

    total = len(all_signals)
    return {
        "schema": "A1_CLAUDE_MG_OPENLOW_STRENGTH_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "ticker_count": len(per_ticker),
        "min_chg_pct": min_chg_pct,
        "max_bar_index": max_bar_index,
        "min_prior_day_range_pct": min_prior_day_range_pct,
        "rungs": list(rungs),
        "strength_target_pct": strength_target_pct,
        "totals": {
            "signals": total,
            "tp1_hits": sum(1 for s in all_signals if s["result"] in ("TP1", "TP2")),
            "tp2_hits": sum(1 for s in all_signals if s["result"] == "TP2"),
            "reached_strength": len(strong),
            "p_reach_strength_given_signal": (len(strong) / total) if total else None,
        },
        "outcome": {
            "note": (
                "Measured from the signal price on same-date forward bars, label-only. "
                "A FAIL result means the next rung went untouched; it does NOT by itself "
                "mean the signal ended negative. These blocks separate the two."
            ),
            "all_signals": outcome_block(all_signals),
            "tp1_or_better": outcome_block([s for s in all_signals if s["result"] in ("TP1", "TP2")]),
            "rung_fail": outcome_block([s for s in all_signals if s["result"] == "FAIL"]),
        },
        "strength_contrast": {
            "note": (
                "Features measured AT SIGNAL TIME ONLY. A separation here is a lead for a "
                "stricter gate; it is not itself a validated filter."
            ),
            f"reached_{int(strength_target_pct)}pct": contrast(strong),
            "did_not_reach": contrast(weak),
        },
        "days": days_out,
        "outcome_is_evaluation_only_not_formula_input": True,
        "winner_only_filter_used": False,
    }


def _print_utf8(text: str) -> None:
    """Print without letting a narrow console codec kill a finished analysis."""
    stream = sys.stdout
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _money(value: float | None) -> str:
    """IDX prices print with a dot thousands separator; absent stays visible."""
    if value is None:
        return "—"
    return f"{round(value):,}".replace(",", ".")


def render_report(payload: Mapping[str, Any], *, strength_only: bool) -> str:
    months = {
        "01": "JAN", "02": "FEB", "03": "MAR", "04": "APR", "05": "MAY", "06": "JUN",
        "07": "JUL", "08": "AUG", "09": "SEP", "10": "OCT", "11": "NOV", "12": "DEC",
    }
    target = int(payload.get("strength_target_pct") or 10)
    key = f"reached_{target}pct"
    header_scope = f" | STRONG≥{target}% ONLY" if strength_only else ""
    lines = [
        f"👀 MULAI GENIT — {payload.get('source_name')} | REPLAY{header_scope}",
        "RESEARCH RENDERING ONLY — NOT A TELEGRAM PUBLICATION.",
        "",
    ]

    for day in payload.get("days", []):
        signals = [s for s in day["signals"] if s[key]] if strength_only else day["signals"]
        parts = day["date"].split("-")
        label = f"{parts[2]} {months.get(parts[1], parts[1])}"
        lines.append(
            f"{label} | OPEN=LOW SCOUT {day['scout_count']} | SIGNAL {day['signal_count']} "
            f"| TP1 {day['tp1_count']} | TP2 {day['tp2_count']} | ≥{target}% {day['strength_count']}"
        )
        if not signals:
            # Telegram Sub-Sub Master section 7: a valid scan with zero results
            # renders this symbol. It must never be used to disguise a feed,
            # scanner, bridge or delivery failure -- this run completed, so the
            # zero is a real zero.
            lines.append("========")
            lines.append("")
            continue
        for s in signals:
            price = _money(s.get("price"))
            tp1 = _money(s.get("tp1_price"))
            tp2 = _money(s.get("tp2_price"))
            mark = {"TP2": "TP2✅", "TP1": "TP1✅", "FAIL": "FAIL"}[s["result"]]
            flag = " ★" if s[key] else ""
            eod = s.get("eod_pct")
            mae = s.get("mae_pct")
            tail = ""
            if eod is not None and mae is not None:
                tail = f" | EOD {eod:+6.2f}% | MAE {mae:+6.2f}%"
            lines.append(
                f"{s['slot']} {s['ticker']:<5}| {price:>8} | {s['chg_pct']:+6.2f}% | "
                f"{tp1:>8} | {tp2:>8} | {mark}{flag}{tail}"
            )
        lines.append("")

    totals = payload.get("totals") or {}
    lines.append(
        f"TOTAL: signals={totals.get('signals')} tp1={totals.get('tp1_hits')} "
        f"tp2={totals.get('tp2_hits')} reached≥{target}%={totals.get('reached_strength')} "
        f"P(≥{target}%|signal)={totals.get('p_reach_strength_given_signal')}"
    )

    outcome = payload.get("outcome") or {}
    if outcome:
        lines.append("")
        lines.append("--- DID IT END MINUS? (from signal price, same day) ---")
        for label, block_key in (
            ("ALL SIGNALS", "all_signals"),
            ("TP1 OR BETTER", "tp1_or_better"),
            ("RUNG FAIL", "rung_fail"),
        ):
            block = outcome.get(block_key) or {}
            if not block.get("n"):
                continue
            lines.append(
                f"{label:<14} n={block['n']:<4} EOD+ {block['eod_positive']:<4} "
                f"EOD0 {block['eod_flat']:<4} EOD- {block['eod_negative']:<4} "
                f"P(+)={block['p_eod_positive']:.3f}"
            )
            lines.append(
                f"{'':<14} EOD Q10 {block['eod_q10_pct']:+6.2f}%  Q25 {block['eod_q25_pct']:+6.2f}%  "
                f"MED {block['eod_median_pct']:+6.2f}%  Q75 {block['eod_q75_pct']:+6.2f}%  "
                f"Q90 {block['eod_q90_pct']:+6.2f}%"
            )
            lines.append(
                f"{'':<14} MAE MED {block['mae_median_pct']:+6.2f}%  Q10 {block['mae_q10_pct']:+6.2f}%  "
                f"MAE-before-peak MED {block['mae_before_peak_median_pct']:+6.2f}%  "
                f"MFE MED {block['mfe_median_pct']:+6.2f}%"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-mg-openlow-strength-v1")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--min-chg-pct", type=float, default=3.5)
    parser.add_argument("--rungs", default=",".join(str(r) for r in DEFAULT_RUNGS))
    parser.add_argument("--strength-target-pct", type=float, default=10.0)
    parser.add_argument("--max-bar-index", type=int, default=None,
                        help="Gate: refuse signals later than this bar. Omit to disable.")
    parser.add_argument("--min-prior-day-range-pct", type=float, default=None,
                        help="Gate: require the previous day to have ranged at least this much.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-output", default=None)
    parser.add_argument("--strength-report-output", default=None)
    args = parser.parse_args(argv)

    rungs = tuple(float(x) for x in args.rungs.split(",") if x.strip())
    payload = analyse(
        args.source_name,
        min_chg_pct=args.min_chg_pct,
        rungs=rungs,
        strength_target_pct=args.strength_target_pct,
        max_bar_index=args.max_bar_index,
        min_prior_day_range_pct=args.min_prior_day_range_pct,
    )
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    full = render_report(payload, strength_only=False)
    # Results are persisted BEFORE anything is printed. The console is not a
    # reliable sink -- a Windows runner's cp1252 stdout cannot encode the report's
    # emoji, and a crash there would otherwise destroy a completed analysis.
    if args.report_output:
        Path(args.report_output).write_text(full + "\n", encoding="utf-8")
    if args.strength_report_output:
        Path(args.strength_report_output).write_text(
            render_report(payload, strength_only=True) + "\n", encoding="utf-8"
        )

    _print_utf8(full)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
