from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_replay import MG_VARIANTS, _num, evaluate_mg_packet


def build_daily_report(
    *,
    source_name: str,
    trading_date: str,
    variant: str,
    params: CandidateParams,
) -> dict[str, Any]:
    if variant not in MG_VARIANTS:
        raise ValueError(f"UNKNOWN_MG_VARIANT:{variant}")
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)

    target_packets: dict[str, list[dict[str, Any]]] = {}
    prior_close: dict[str, float] = {}
    prior_date: dict[str, str] = {}
    scanned_packets = 0

    for _manifest_row, packet in reader.iter_packets():
        all_bars, _mapping = packet_to_formula_bars(packet)
        bars = [bar for bar in all_bars if bar["session_eligible"]]
        scanned_packets += 1
        ticker = str(packet.identity.ticker)
        date = str(packet.identity.trading_date)
        closes = [
            float(bar["close"])
            for bar in bars
            if bar.get("close") is not None and float(bar["close"]) > 0
        ]
        if date < trading_date and closes:
            if ticker not in prior_date or date > prior_date[ticker]:
                prior_date[ticker] = date
                prior_close[ticker] = closes[-1]
        elif date == trading_date and bars:
            target_packets[ticker] = bars

    slot_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    slot_unavailable_targets: dict[str, list[str]] = defaultdict(list)
    all_slots: set[str] = set()

    for ticker, bars in target_packets.items():
        mg_rows = evaluate_mg_packet(bars, params)
        for i, row in enumerate(mg_rows):
            if not row["publication_slot"]:
                continue
            timestamp = str(row["timestamp"])
            all_slots.add(timestamp)
            if row["variants"][variant] != TRUE:
                continue
            close = _num(bars[i].get("close"))
            tp1 = _num(row["targets"].get("tp1"))
            tp2 = _num(row["targets"].get("tp2"))
            if tp1 is None or tp2 is None:
                slot_unavailable_targets[timestamp].append(ticker)
                continue
            prev = prior_close.get(ticker)
            chg_pct = (
                (float(close) / prev - 1.0) * 100.0
                if close is not None and prev not in (None, 0.0)
                else None
            )
            slot_rows[timestamp].append(
                {
                    "CODE": ticker,
                    "PRICE": close,
                    "CHG%": chg_pct,
                    "TP-1": tp1,
                    "TP-2": tp2,
                }
            )

    slots: list[dict[str, Any]] = []
    previous_codes: set[str] = set()
    seen_codes: set[str] = set()
    for timestamp in sorted(all_slots):
        rows = sorted(slot_rows.get(timestamp, []), key=lambda row: str(row["CODE"]))
        current_codes = {str(row["CODE"]) for row in rows}
        new_codes = sorted(current_codes - seen_codes)
        returned_codes = sorted((current_codes - previous_codes) & seen_codes)
        continued_codes = sorted(current_codes & previous_codes)
        dropped_codes = sorted(previous_codes - current_codes)
        slots.append(
            {
                "as_of": timestamp,
                "display_time": datetime.fromisoformat(timestamp).strftime("%H:%M"),
                "candidate_count": len(rows),
                "new_codes": new_codes,
                "continued_codes": continued_codes,
                "returned_codes": returned_codes,
                "dropped_codes": dropped_codes,
                "suppressed_target_unavailable": sorted(slot_unavailable_targets.get(timestamp, [])),
                "telegram_zero_match_render": "========" if not rows else None,
                "rows": rows,
            }
        )
        seen_codes.update(current_codes)
        previous_codes = current_codes

    return {
        "schema": "A1_TELEGRAM_MG_DAILY_5M_TAPE_V1",
        "status": "RESEARCH_REPORT_NOT_CANONICAL",
        "source_identity": reader.identity.as_dict(),
        "trading_date": trading_date,
        "variant": variant,
        "variant_status": "RESEARCH_CANDIDATE_NOT_FINAL",
        "telegram_family": "EARLY_POTENTIAL",
        "telegram_public_name": "MULAI_GENIT",
        "telegram_output_contract": "CODE | PRICE | CHG% | TP-1 | TP-2",
        "params": params.__dict__,
        "scanned_source_packets": scanned_packets,
        "target_ticker_count": len(target_packets),
        "prior_close_available_ticker_count": len(prior_close),
        "slot_count": len(slots),
        "slots": slots,
        "future_data_used_for_candidate_state": False,
        "winner_only_filter_used": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-daily-report")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--effort-lookback", type=int, required=True)
    parser.add_argument("--progress-lookback", type=int, required=True)
    parser.add_argument("--high-lookback", type=int, required=True)
    parser.add_argument("--recovery-lookback", type=int, required=True)
    parser.add_argument("--low-stabilization-bars", type=int, required=True)
    parser.add_argument("--early-checkpoint-bar", type=int, required=True)
    parser.add_argument("--late-lift-min-bar", type=int, required=True)
    args = parser.parse_args(argv)

    params = CandidateParams(
        effort_lookback=args.effort_lookback,
        progress_lookback=args.progress_lookback,
        high_lookback=args.high_lookback,
        recovery_lookback=args.recovery_lookback,
        low_stabilization_bars=args.low_stabilization_bars,
        early_checkpoint_bar=args.early_checkpoint_bar,
        late_lift_min_bar=args.late_lift_min_bar,
    )
    report = build_daily_report(
        source_name=args.source_name,
        trading_date=args.trading_date,
        variant=args.variant,
        params=params,
    )
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(
        name=f"TELEGRAM_MG_DAILY_REPORT__{safe_request}.json",
        obj=report,
    )
    print(json.dumps({"pass": True, "report": report, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
