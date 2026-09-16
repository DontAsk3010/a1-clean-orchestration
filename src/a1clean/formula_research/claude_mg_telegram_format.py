"""Render MG research signals into the governed Telegram output contract.

RESEARCH_ONLY. This is a PRESENTATION renderer over research output. It is not
a Telegram publisher, it opens no promotion path, and it does not compute
anything: every value it prints is read from a governed run's result JSON.
Master §17 requires Telegram to be a presentation layer that never becomes a
second analytical engine, so this module deliberately contains no thresholds,
no scoring, no selection logic, and no target arithmetic.

Output contract (Branch 07 Formula Research Handbook
`1sQu0l2qwvsjItmBycRh3siMajKEQknHOMBLlBQd3I-Q` §3):

    CODE | PRICE | CHG% | TP-1 | TP-2

published at the first automatic snapshot then every 5 minutes, with TP-1/TP-2
dynamic per snapshot and never calculated Telegram-side.

--------------------------------------------------------------------------
HONEST LIMITATION OF WHAT THIS CAN CURRENTLY SHOW
--------------------------------------------------------------------------
The governed MG feed republishes a ticker at every slot for as long as it still
qualifies, and drops it when it stops. The research module upstream of this
renderer deliberately keeps only the FIRST qualifying snapshot per ticker-day,
so that one persistent opportunity is not counted as dozens of independent wins
in the outcome statistics. Those two behaviours are different on purpose.

Therefore the rendered feed below shows FIRST APPEARANCES, not the full
republish-and-disappear lifecycle. It is a faithful rendering of the contract's
row format against real signals; it is not yet a faithful simulation of the
live feed's persistence behaviour. Reading it as the latter would overstate
what has been built.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

COLUMNS = ("CODE", "PRICE", "CHG%", "TP-1", "TP-2")


def _format_price(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    return f"{round(value):,}".replace(",", ".")


def _format_chg(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    return f"{value:+.2f}%"


def _slot_of(signal: Mapping[str, Any]) -> str:
    ts = signal.get("timestamp")
    if not ts:
        return "UNKNOWN_TIME"
    return str(ts)


def render_rows(signals: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """One contract row per signal. Values are read, never recomputed."""
    rows = []
    for signal in signals:
        published = signal.get("published") or {}
        rows.append(
            {
                "CODE": str(signal.get("ticker") or "UNKNOWN"),
                "PRICE": _format_price(published.get("price")),
                "CHG%": _format_chg(published.get("chg_pct")),
                "TP-1": _format_price(published.get("tp1")),
                "TP-2": _format_price(published.get("tp2")),
            }
        )
    return rows


def group_by_slot(signals: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for signal in signals:
        grouped[_slot_of(signal)].append(signal)
    return dict(sorted(grouped.items()))


def render_slot_table(slot: str, signals: Sequence[Mapping[str, Any]]) -> str:
    rows = render_rows(signals)
    widths = {col: len(col) for col in COLUMNS}
    for row in rows:
        for col in COLUMNS:
            widths[col] = max(widths[col], len(row[col]))

    header = " | ".join(col.ljust(widths[col]) for col in COLUMNS)
    rule = "-+-".join("-" * widths[col] for col in COLUMNS)
    body = [
        " | ".join(row[col].rjust(widths[col]) if col != "CODE" else row[col].ljust(widths[col]) for col in COLUMNS)
        for row in rows
    ]
    return "\n".join([f"[{slot}]  ({len(rows)} ticker)", header, rule, *body])


def render_feed(signals: Sequence[Mapping[str, Any]], *, max_slots: int | None = None) -> str:
    grouped = group_by_slot(signals)
    slots = list(grouped.items())
    truncated = 0
    if max_slots is not None and len(slots) > max_slots:
        truncated = len(slots) - max_slots
        slots = slots[:max_slots]
    blocks = [render_slot_table(slot, rows) for slot, rows in slots]
    if truncated:
        blocks.append(f"... {truncated} further snapshot slot(s) not shown ...")
    return "\n\n".join(blocks) if blocks else "(no signals — the formula published nothing for this source)"


def _extract_signals(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if isinstance(payload.get("signals"), list):
        return list(payload["signals"])
    best = payload.get("signals_for_selected_thresholds")
    if isinstance(best, list):
        return list(best)
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-claude-mg-telegram-format")
    parser.add_argument("--result", required=True, help="Result JSON from a governed MG research run")
    parser.add_argument("--max-slots", type=int, default=12)
    parser.add_argument("--output", default=None, help="Optional file to write the rendered feed to")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    signals = _extract_signals(payload)
    feed = render_feed(signals, max_slots=args.max_slots)

    banner = (
        "RESEARCH RENDERING ONLY — NOT A TELEGRAM PUBLICATION.\n"
        f"source={payload.get('source_name')} schema={payload.get('schema')} "
        f"status={payload.get('status')}\n"
        f"signals_rendered={len(signals)}\n"
        "Rows show FIRST APPEARANCE per ticker-day, not the live feed's "
        "republish-while-qualifying behaviour.\n"
    )
    text = banner + "\n" + feed
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
