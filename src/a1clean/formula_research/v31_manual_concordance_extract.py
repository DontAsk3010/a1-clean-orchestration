from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import telegram_mg_structure_v12_runner as v12r
from .full_chronological_cache_catalog import prepare_full_chronological_sources
from .haka_haki_reconstruction import DEC_2024_CONTRACT
from .v30_semantic_journey_enrichment import enrich_ticker_day
from .v31_full_chronological_semantic_enrichment import _rewrite_lineage

SCHEMA = "A1_V31_MANUAL_CONCORDANCE_EXTRACT_V1"
TARGET_TICKER = "AALI"
TARGET_DATES = ("2024-12-02", "2024-12-03", "2024-12-04")


def _carry_from_packet(packet: dict[str, Any], source: str, previous_day: str) -> dict[str, Any]:
    bars = [dict(x) for x in packet.get("bars", [])]
    return {
        "status": "EXACT_PREVIOUS_GOVERNED_DATE_PACKET",
        "previous_governed_date": previous_day,
        "source": source,
        "bar_count": len(bars),
        "first_timestamp": str(bars[0].get("timestamp") or "") if bars else None,
        "last_timestamp": str(bars[-1].get("timestamp") or "") if bars else None,
        "final_close": bars[-1].get("close") if bars else None,
    }


def extract() -> dict[str, Any]:
    plan = prepare_full_chronological_sources(ensure_cache=False)
    source = str(DEC_2024_CONTRACT["source_name"])
    src = next(x for x in plan["sources"] if str(x["source_name"]) == source)

    packets: dict[str, dict[str, Any]] = {}
    for packet in v12r._iter_cached(source):
        if str(packet.get("ticker") or "") != TARGET_TICKER:
            continue
        day = str(packet.get("date") or "")
        if day in TARGET_DATES:
            packets[day] = dict(packet)
        if len(packets) == len(TARGET_DATES):
            break

    missing = [d for d in TARGET_DATES if d not in packets]
    if missing:
        raise RuntimeError(f"V31_CONCORDANCE_TARGET_MISSING:{missing}")

    cases: list[dict[str, Any]] = []
    prev_packet: dict[str, Any] | None = None
    prev_day: str | None = None
    for day in TARGET_DATES:
        packet = packets[day]
        bars = [dict(x) for x in packet.get("bars", [])]
        carry = (
            _carry_from_packet(prev_packet, source, prev_day)
            if prev_packet is not None and prev_day is not None
            else None
        )
        td, runs, journeys = enrich_ticker_day(
            bars,
            source=source,
            source_identity=src,
            ticker=TARGET_TICKER,
            trading_date=day,
            carry_in=carry,
            previous_governed_date=prev_day,
            allow_haka_haki=True,
        )
        td = _rewrite_lineage(td)
        runs = [_rewrite_lineage(dict(x)) for x in runs]
        journeys = [_rewrite_lineage(dict(x)) for x in journeys]
        cases.append(
            {
                "ticker": TARGET_TICKER,
                "date": day,
                "source": source,
                "source_identity": {
                    "source_drive_id": src.get("source_drive_id"),
                    "source_sha256": src.get("source_sha256"),
                    "generation_id": src.get("generation_id"),
                    "semantic_manifest_fingerprint": src.get("semantic_manifest_fingerprint"),
                },
                "carry_in": carry,
                "bars": bars,
                "ticker_day": td,
                "formation_runs": runs,
                "event_journeys": journeys,
            }
        )
        prev_packet = packet
        prev_day = day

    return {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": "READ_ONLY_CONCORDANCE_AUDIT",
        "v31_corpus_digest_sha256": plan["corpus_digest_sha256"],
        "ticker": TARGET_TICKER,
        "dates": list(TARGET_DATES),
        "cases": cases,
        "contract": {
            "engine_logic_modified": False,
            "v31_outputs_rewritten": False,
            "manual_labels_used_as_target": False,
            "read_only_extract_from_passed_v31_inputs": True,
            "causal_and_hindsight_fields_preserved": True,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    a = p.parse_args()
    out = extract()
    Path(a.output).write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": out["schema"],
                "status": out["status"],
                "ticker": out["ticker"],
                "dates": out["dates"],
                "bar_counts": {x["date"]: len(x["bars"]) for x in out["cases"]},
                "formation_run_counts": {x["date"]: len(x["formation_runs"]) for x in out["cases"]},
                "event_journey_counts": {x["date"]: len(x["event_journeys"]) for x in out["cases"]},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
