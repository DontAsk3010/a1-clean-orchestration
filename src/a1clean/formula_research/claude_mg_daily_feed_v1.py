"""Full-month MG publication feed: every trading day, every 5-minute slot.

RESEARCH_ONLY. Reconstructs what the governed MG family would have published
across a whole source month, so the owner can see which tickers appear on which
day and in which 5-minute slot.

--------------------------------------------------------------------------
HOW THIS DIFFERS FROM THE DISCOVERY MODULE, AND WHY BOTH EXIST
--------------------------------------------------------------------------
`claude_mg_intraday_v2` keeps only the FIRST qualifying snapshot per ticker-day,
deliberately, so that one persistent opportunity cannot be counted as dozens of
independent wins in the outcome statistics.

The live feed behaves the opposite way: a ticker is republished at every slot
for as long as it still qualifies, and disappears when it stops. This module
reproduces that behaviour. It reuses `claude_mg_intraday_v2`'s state and gate
functions unchanged, so the feed can never drift from the researched candidate
-- only the emission policy differs.

--------------------------------------------------------------------------
BAR RESOLUTION VS PUBLICATION SLOT
--------------------------------------------------------------------------
The governed source is minute-resolution (observed timestamps land on 09:04,
09:07, 11:29 and so on, and the physical fields are named *_1M). The MG contract
publishes every 5 minutes. Evaluation therefore runs at native bar resolution
and each qualifying bar is assigned to the 5-minute slot that CONTAINS it by
flooring the minute. Within one slot a ticker is published once, carrying its
latest qualifying state in that slot -- publishing the same ticker several times
inside a single 5-minute window would misrepresent the contract.

Slots are derived from the actual source timestamps. No fixed clock is imposed
as a filter, per the Master's no-universal-cutoff rule; `--from-time` only
controls what is DISPLAYED, never what is read or evaluated.

--------------------------------------------------------------------------
PRE-OPEN
--------------------------------------------------------------------------
Rows carrying neither regular-session flag and falling before the day's first
regular bar are counted and reported separately as pre-open-candidate rows, with
their earliest observed times. They are NOT published into the feed: the MG
contract begins at the first automatic snapshot at 09:00 WIB, and the candidate
gates were never researched against pre-open mechanics. Their presence is
reported as evidence of what the source actually carries, which is a different
question from what the contract publishes, and the two are not conflated here.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..pattern_discovery.source_reader import GovernedSourceReader
from ..google_drive import build_drive_api
from .formula_replay import packet_to_formula_bars
from .claude_mg_intraday_v2 import (
    MIN_CONSTRUCTIVE_BARS,
    MGIntradayThresholds,
    _day_summary,
    _evaluate_snapshot,
    _intraday_view,
    _learn_thresholds,
    _precursor_block,
    _process_ticker,
    _reject_oos_source,
)


def _slot_of(timestamp: str | None, minutes: int) -> tuple[str, str] | None:
    """('YYYY-MM-DD', 'HH:MM') for the slot containing this bar, or None."""
    if not timestamp or " " not in timestamp:
        return None
    date_part, time_part = timestamp.split(" ", 1)
    pieces = time_part.split(":")
    if len(pieces) < 2:
        return None
    try:
        hour, minute = int(pieces[0]), int(pieces[1])
    except ValueError:
        return None
    return date_part, f"{hour:02d}:{(minute // minutes) * minutes:02d}"


def _preopen_rows(bars: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Rows before the first regular-session bar that carry neither session flag."""
    first_regular = next(
        (i for i, b in enumerate(bars) if b.get("regular_session1") or b.get("regular_session2")),
        None,
    )
    if first_regular is None:
        return []
    return [
        b
        for b in bars[:first_regular]
        if not b.get("regular_session1") and not b.get("regular_session2")
    ]


def build_feed(
    source_name: str,
    *,
    precursor_window_days: int,
    slot_minutes: int,
    min_streak: int | None,
) -> dict[str, Any]:
    _reject_oos_source(source_name)
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)

    ticker_sessions: dict[str, list[dict[str, Any]]] = {}
    preopen_row_count = 0
    preopen_day_count = 0
    preopen_earliest: dict[str, str] = {}

    for _row, packet in reader.iter_packets():
        bars, _mapping = packet_to_formula_bars(packet)
        ticker = str(packet.identity.ticker)
        ticker_sessions.setdefault(ticker, []).append(
            {"trading_date": packet.identity.trading_date, "bars": bars}
        )
        pre = _preopen_rows(bars)
        if pre:
            preopen_day_count += 1
            preopen_row_count += len(pre)
            date = str(packet.identity.trading_date)
            earliest = min(str(b.get("timestamp") or "") for b in pre)
            if earliest and (date not in preopen_earliest or earliest < preopen_earliest[date]):
                preopen_earliest[date] = earliest

    # Learn thresholds exactly as the discovery phase does, so the feed reflects
    # the researched candidate rather than a separately tuned one.
    pools: dict[str, list[float]] = {}
    for ticker, sessions in ticker_sessions.items():
        _s, _r, ticker_pools = _process_ticker(ticker, sessions, None, [60])
        for name, values in ticker_pools.items():
            pools.setdefault(name, []).extend(values)
    thresholds = _learn_thresholds(
        pools,
        precursor_window_days=precursor_window_days,
        min_streak=min_streak if min_streak is not None else 4,
    )

    # date -> slot -> ticker -> published fields (last qualifying state in slot)
    feed: dict[str, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    qualifying_bar_count = 0

    for ticker, sessions in ticker_sessions.items():
        ordered = sorted(sessions, key=lambda s: s["trading_date"])
        daily: list[dict[str, Any]] = []
        day_bars: list[list[Mapping[str, Any]]] = []
        for s in ordered:
            summary = _day_summary(s["bars"])
            if summary is None:
                continue
            daily.append(summary)
            day_bars.append([b for b in s["bars"] if b.get("session_eligible")])

        for day_idx in range(len(daily)):
            if day_idx < precursor_window_days + 1:
                continue
            bars = day_bars[day_idx]
            if len(bars) < MIN_CONSTRUCTIVE_BARS:
                continue
            ctx = _precursor_block(daily, day_idx, thresholds)
            if ctx is None:
                continue
            for t in range(MIN_CONSTRUCTIVE_BARS - 1, len(bars)):
                view = _intraday_view(bars, t)
                if view is None:
                    continue
                fires, _reason, published = _evaluate_snapshot(view, ctx, thresholds)
                if not fires:
                    continue
                slot = _slot_of(bars[t].get("timestamp"), slot_minutes)
                if slot is None:
                    continue
                date, hhmm = slot
                qualifying_bar_count += 1
                feed[date][hhmm][ticker] = {
                    "price": published["price"],
                    "chg_pct": published["chg_pct"],
                    "tp1": published["tp1"],
                    "tp2": published["tp2"],
                }

    days = []
    for date in sorted(feed):
        slots = []
        day_tickers: set[str] = set()
        for hhmm in sorted(feed[date]):
            tickers = feed[date][hhmm]
            day_tickers.update(tickers)
            slots.append(
                {
                    "slot": hhmm,
                    "ticker_count": len(tickers),
                    "tickers": [{"code": code, **fields} for code, fields in sorted(tickers.items())],
                }
            )
        days.append(
            {
                "date": date,
                "slot_count": len(slots),
                "unique_ticker_count": len(day_tickers),
                "unique_tickers": sorted(day_tickers),
                "slots": slots,
            }
        )

    all_dates = sorted({str(s["trading_date"]) for sessions in ticker_sessions.values() for s in sessions})

    return {
        "schema": "A1_CLAUDE_MG_DAILY_FEED_V1",
        "status": "RESEARCH_RESULT_NOT_CANONICAL",
        "source_name": source_name,
        "slot_minutes": slot_minutes,
        "ticker_count": len(ticker_sessions),
        "trading_dates_in_source": len(all_dates),
        "trading_dates_with_any_publication": len(days),
        "qualifying_bars_total": qualifying_bar_count,
        "learned_thresholds": thresholds.as_dict(),
        "preopen_candidate_rows": {
            "note": (
                "Rows before the first regular-session bar carrying neither session flag. "
                "Counted as source evidence; NOT published -- the MG contract starts at the "
                "first automatic snapshot and these gates were never researched against "
                "pre-open mechanics."
            ),
            "ticker_days_with_such_rows": preopen_day_count,
            "total_rows": preopen_row_count,
            "earliest_observed_time_per_date": dict(sorted(preopen_earliest.items())),
        },
        "days": days,
        "outcome_is_evaluation_only_not_formula_input": True,
        "future_data_used_for_candidate_state": False,
    }


def render_feed_text(payload: Mapping[str, Any], *, from_time: str | None, max_rows_per_day: int) -> str:
    lines = [
        "RESEARCH RENDERING ONLY - NOT A TELEGRAM PUBLICATION.",
        f"source={payload.get('source_name')} slot={payload.get('slot_minutes')}min "
        f"tickers={payload.get('ticker_count')}",
        f"trading dates in source={payload.get('trading_dates_in_source')} | "
        f"dates with any publication={payload.get('trading_dates_with_any_publication')}",
        "",
    ]
    pre = payload.get("preopen_candidate_rows") or {}
    lines.append(
        f"pre-open candidate rows in source: {pre.get('total_rows')} across "
        f"{pre.get('ticker_days_with_such_rows')} ticker-days (counted, NOT published)"
    )
    lines.append("")

    for day in payload.get("days", []):
        lines.append(f"===== {day['date']} — {day['unique_ticker_count']} ticker, {day['slot_count']} slot =====")
        shown = 0
        for slot in day["slots"]:
            if from_time and slot["slot"] < from_time:
                continue
            if shown >= max_rows_per_day:
                lines.append(f"  ... remaining slots for {day['date']} omitted from this rendering ...")
                break
            codes = "  ".join(
                f"{t['code']} {round(t['price']):,}".replace(",", ".") + f" {t['chg_pct']:+.2f}%"
                for t in slot["tickers"]
            )
            lines.append(f"  [{slot['slot']}] {codes}")
            shown += 1
        lines.append("")
    if not payload.get("days"):
        lines.append("(no publications at all for this source — the formula published nothing)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-mg-daily-feed-v1")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--precursor-window-days", type=int, default=8)
    parser.add_argument("--slot-minutes", type=int, default=5)
    parser.add_argument("--min-streak", type=int, default=4)
    parser.add_argument("--from-time", default="09:00", help="Display filter only; never filters evaluation")
    parser.add_argument("--max-slots-per-day", type=int, default=200)
    parser.add_argument("--output", required=True)
    parser.add_argument("--text-output", default=None)
    args = parser.parse_args(argv)

    payload = build_feed(
        args.source_name,
        precursor_window_days=args.precursor_window_days,
        slot_minutes=args.slot_minutes,
        min_streak=args.min_streak,
    )
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    text = render_feed_text(payload, from_time=args.from_time, max_rows_per_day=args.max_slots_per_day)
    print(text)
    if args.text_output:
        Path(args.text_output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
