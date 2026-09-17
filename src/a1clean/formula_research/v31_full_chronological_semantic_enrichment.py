from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from . import telegram_mg_structure_v12_runner as v12r
from .full_chronological_cache_catalog import (
    EXPECTED_FULL_SOURCE_COUNT,
    EXPECTED_LEGACY_MINUTE_ROWS,
    EXPECTED_LEGACY_SOURCE_COUNT,
    EXPECTED_LEGACY_TICKER_DAYS,
    MARCH_2025_SOURCE,
    prepare_full_chronological_sources,
)
from .haka_haki_reconstruction import DEC_2024_CONTRACT
from .v30_semantic_journey_enrichment import (
    SCHEMA as V30_ENGINE_SCHEMA,
    _build_day_index,
    _digest_obj,
    _safe_float,
    _slug,
    _write_gz_jsonl,
    enrich_ticker_day,
)

SCHEMA = "A1_V31_FULL_CHRONOLOGICAL_SEMANTIC_ENRICHMENT_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
BASELINE_V26_RUN_ID = 35261173652
BASELINE_V26_ARTIFACT_ID = 10523725224
BASELINE_V26_ARTIFACT_DIGEST = "sha256:efec3347d5f95b42684ccb77b1b7aada1d9520b6b3e1ac6596edb817b6d5047a"


def _carry_for_full(
    db: sqlite3.Connection,
    *,
    ticker: str,
    day: str,
) -> tuple[dict[str, Any] | None, str | None]:
    row = db.execute("SELECT previous_day FROM calendar WHERE day=?", (day,)).fetchone()
    prev_day = str(row[0]) if row and row[0] else None
    if prev_day is None:
        return None, None
    prior = db.execute(
        "SELECT source,bar_count,first_timestamp,last_timestamp,final_close "
        "FROM days WHERE ticker=? AND day=? ORDER BY source_order DESC LIMIT 1",
        (ticker, prev_day),
    ).fetchone()
    if prior is None:
        return {
            "status": "NO_TICKER_PACKET_ON_PREVIOUS_GOVERNED_DATE",
            "previous_governed_date": prev_day,
        }, prev_day
    return {
        "status": "EXACT_PREVIOUS_GOVERNED_DATE_PACKET",
        "previous_governed_date": prev_day,
        "source": prior[0],
        "bar_count": int(prior[1]),
        "first_timestamp": prior[2],
        "last_timestamp": prior[3],
        "final_close": prior[4],
    }, prev_day


def _checkpoint_ok(path: Path, src: Mapping[str, Any], corpus_digest: str) -> bool:
    if not path.is_file():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        obj.get("schema") == SCHEMA
        and obj.get("status") == "PASS"
        and obj.get("corpus_digest_sha256") == corpus_digest
        and obj.get("source") == src.get("source_name")
        and obj.get("source_sha256") == src.get("source_sha256")
        and int(obj.get("ticker_days", -1)) == int(src.get("ticker_days", -2))
        and int(obj.get("minute_rows", -1)) == int(src.get("rows", -2))
    )


def _rewrite_lineage(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["semantic_engine_parent_schema"] = V30_ENGINE_SCHEMA
    out["schema"] = SCHEMA
    out["lineage_version"] = "V3.1_FULL_CHRONOLOGICAL"
    return out


def run(
    *,
    output_root: Path,
    expected_v26_artifact_digest: str,
) -> dict[str, Any]:
    if expected_v26_artifact_digest != BASELINE_V26_ARTIFACT_DIGEST:
        raise RuntimeError(
            f"V31_V26_BASELINE_DIGEST_MISMATCH:{expected_v26_artifact_digest}"
        )

    plan = prepare_full_chronological_sources(ensure_cache=True)
    sources = list(plan["sources"])
    corpus_digest = str(plan["corpus_digest_sha256"])

    if int(plan["source_count"]) != EXPECTED_FULL_SOURCE_COUNT:
        raise RuntimeError("V31_FULL_SOURCE_COUNT_FAIL")
    if int(plan["legacy_source_count"]) != EXPECTED_LEGACY_SOURCE_COUNT:
        raise RuntimeError("V31_LEGACY_SOURCE_COUNT_FAIL")
    if int(plan["legacy_ticker_days"]) != EXPECTED_LEGACY_TICKER_DAYS:
        raise RuntimeError("V31_LEGACY_TICKER_DAY_BASELINE_FAIL")
    if int(plan["legacy_minute_rows"]) != EXPECTED_LEGACY_MINUTE_ROWS:
        raise RuntimeError("V31_LEGACY_MINUTE_ROW_BASELINE_FAIL")
    if int(plan["march_ticker_days"]) <= 0 or int(plan["march_minute_rows"]) <= 0:
        raise RuntimeError("V31_MARCH_SOURCE_EMPTY")

    output_root.mkdir(parents=True, exist_ok=True)
    index_path = output_root / "day-index.sqlite3"
    db = sqlite3.connect(index_path)
    dates, indexed_days, indexed_rows = _build_day_index(db, sources)
    if indexed_days != int(plan["full_ticker_days"]) or indexed_rows != int(plan["full_minute_rows"]):
        raise RuntimeError(
            f"V31_INDEX_RECONCILIATION_FAIL:{indexed_days}:{indexed_rows}:"
            f"{plan['full_ticker_days']}:{plan['full_minute_rows']}"
        )

    chronology = dict(plan["chronology"])
    april_first = str(chronology["april_first_date"])
    march_last = str(chronology["march_last_date"])
    row = db.execute("SELECT previous_day FROM calendar WHERE day=?", (april_first,)).fetchone()
    actual_previous = str(row[0]) if row and row[0] else None
    if actual_previous != march_last:
        raise RuntimeError(
            f"V31_MARCH_APRIL_CALENDAR_LINK_FAIL:{actual_previous}:{march_last}"
        )

    totals = Counter()
    source_summaries: list[dict[str, Any]] = []
    sample: list[dict[str, Any]] = []
    reused_sources = 0

    for src in sources:
        source = str(src["source_name"])
        source_dir = output_root / _slug(source)
        source_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = source_dir / "checkpoint.json"

        if _checkpoint_ok(checkpoint, src, corpus_digest):
            cp = json.loads(checkpoint.read_text(encoding="utf-8"))
            source_summaries.append(cp)
            for key in (
                "ticker_days",
                "minute_rows",
                "zero_session_ticker_days",
                "formation_runs",
                "semantic_markers",
                "event_journeys",
                "right_censored_journeys",
                "no_forced_event_ticker_days",
            ):
                totals[key] += int(cp.get(key, 0))
            reused_sources += 1
            continue

        ticker_day_path = source_dir / "ticker-days.jsonl.gz"
        runs_path = source_dir / "formation-runs.jsonl.gz"
        journeys_path = source_dir / "event-journeys.jsonl.gz"
        td_tmp = ticker_day_path.with_suffix(ticker_day_path.suffix + ".tmp")
        r_tmp = runs_path.with_suffix(runs_path.suffix + ".tmp")
        j_tmp = journeys_path.with_suffix(journeys_path.suffix + ".tmp")
        counts = Counter()
        allow_haka_haki = source == str(DEC_2024_CONTRACT["source_name"])

        with gzip.open(td_tmp, "wt", encoding="utf-8", newline="\n") as td_fh,              gzip.open(r_tmp, "wt", encoding="utf-8", newline="\n") as r_fh,              gzip.open(j_tmp, "wt", encoding="utf-8", newline="\n") as j_fh:
            for packet in v12r._iter_cached(source):
                ticker = str(packet.get("ticker") or "")
                day = str(packet.get("date") or "")
                bars = [dict(x) for x in packet.get("bars", [])]
                carry, prev_day = _carry_for_full(db, ticker=ticker, day=day)
                td, runs, journeys = enrich_ticker_day(
                    bars,
                    source=source,
                    source_identity=src,
                    ticker=ticker,
                    trading_date=day,
                    carry_in=carry,
                    previous_governed_date=prev_day,
                    allow_haka_haki=allow_haka_haki,
                )
                td = _rewrite_lineage(td)
                runs = [_rewrite_lineage(dict(x)) for x in runs]
                journeys = [_rewrite_lineage(dict(x)) for x in journeys]

                td_fh.write(
                    json.dumps(td, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    + "\n"
                )
                for rec in runs:
                    r_fh.write(
                        json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                        + "\n"
                    )
                for rec in journeys:
                    j_fh.write(
                        json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                        + "\n"
                    )

                counts["ticker_days"] += 1
                counts["minute_rows"] += len(bars)
                counts["zero_session_ticker_days"] += int(not bars)
                counts["formation_runs"] += len(runs)
                counts["semantic_markers"] += int(td["semantic_marker_count"])
                counts["event_journeys"] += len(journeys)
                counts["right_censored_journeys"] += int(td["open_right_censored_journey_count"])
                counts["no_forced_event_ticker_days"] += int(td["no_forced_event"])
                if len(sample) < 120:
                    sample.append(td)

        td_tmp.replace(ticker_day_path)
        r_tmp.replace(runs_path)
        j_tmp.replace(journeys_path)

        if counts["ticker_days"] != int(src["ticker_days"]) or counts["minute_rows"] != int(src["rows"]):
            raise RuntimeError(
                f"V31_SOURCE_RECONCILIATION_FAIL:{source}:{dict(counts)}:"
                f"{src['ticker_days']}:{src['rows']}"
            )

        cp = {
            "schema": SCHEMA,
            "status": "PASS",
            "research_status": STATUS,
            "corpus_digest_sha256": corpus_digest,
            "source": source,
            "source_drive_id": src.get("source_drive_id"),
            "source_sha256": src.get("source_sha256"),
            "generation_id": src.get("generation_id"),
            "semantic_manifest_fingerprint": src.get("semantic_manifest_fingerprint"),
            "legacy_v2_source": bool(src.get("legacy_v2_source")),
            "march_2025_catchup_source": bool(src.get("march_2025_catchup_source")),
            **{k: int(v) for k, v in counts.items()},
            "ticker_day_file": ticker_day_path.name,
            "formation_run_file": runs_path.name,
            "event_journey_file": journeys_path.name,
            "causal_state_not_rewritten_by_hindsight": True,
            "raw_reread": False,
            "normalized_cache_reused_or_narrowly_built": True,
            "old_v2_artifacts_rewritten": False,
        }
        checkpoint.write_text(json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8")
        source_summaries.append(cp)
        totals.update(counts)

    if totals["ticker_days"] != int(plan["full_ticker_days"]) or totals["minute_rows"] != int(plan["full_minute_rows"]):
        raise RuntimeError(f"V31_GLOBAL_RECONCILIATION_FAIL:{dict(totals)}")

    march_summary = next(
        cp for cp in source_summaries if cp["source"] == MARCH_2025_SOURCE
    )
    if int(march_summary["ticker_days"]) != int(plan["march_ticker_days"]):
        raise RuntimeError("V31_MARCH_TICKER_DAY_RECONCILIATION_FAIL")
    if int(march_summary["minute_rows"]) != int(plan["march_minute_rows"]):
        raise RuntimeError("V31_MARCH_MINUTE_ROW_RECONCILIATION_FAIL")

    sample_path = output_root / "compact-sample.jsonl.gz"
    _write_gz_jsonl(sample_path, sample)

    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "corpus_digest_sha256": corpus_digest,
        "baseline_v26": {
            "run_id": BASELINE_V26_RUN_ID,
            "artifact_id": BASELINE_V26_ARTIFACT_ID,
            "artifact_digest": BASELINE_V26_ARTIFACT_DIGEST,
            "legacy_sources": EXPECTED_LEGACY_SOURCE_COUNT,
            "legacy_ticker_days": EXPECTED_LEGACY_TICKER_DAYS,
            "legacy_minute_rows": EXPECTED_LEGACY_MINUTE_ROWS,
            "preserved_immutable": True,
        },
        "contract": {
            "full_chronological_atlas": True,
            "march_2025_included_as_full_source": True,
            "feb_march_april_continuity_required": True,
            "old_v2_artifacts_immutable": True,
            "failed_v30_run_not_reused_as_pass": True,
            "append_only_new_lineage": True,
            "manual_reference_not_used_as_hidden_label": True,
            "causal_view_separate_from_hindsight": True,
            "no_forced_event": True,
            "unknown_unproven_preserved": True,
            "oos_is_formula_versioned_replay_not_withheld_atlas_month": True,
            "downstream_global_layers_must_be_new_version_if_materially_changed": True,
        },
        "reconciliation": {
            "pass": True,
            "source_count": len(sources),
            "expected_source_count": EXPECTED_FULL_SOURCE_COUNT,
            "ticker_days": int(totals["ticker_days"]),
            "expected_ticker_days": int(plan["full_ticker_days"]),
            "minute_rows": int(totals["minute_rows"]),
            "expected_minute_rows": int(plan["full_minute_rows"]),
            "zero_session_ticker_days": int(totals["zero_session_ticker_days"]),
            "formation_runs": int(totals["formation_runs"]),
            "semantic_markers": int(totals["semantic_markers"]),
            "event_journeys": int(totals["event_journeys"]),
            "right_censored_journeys": int(totals["right_censored_journeys"]),
            "no_forced_event_ticker_days": int(totals["no_forced_event_ticker_days"]),
            "governed_dates": len(dates),
            "reused_pass_sources": reused_sources,
            "march_ticker_days": int(march_summary["ticker_days"]),
            "march_minute_rows": int(march_summary["minute_rows"]),
        },
        "chronology": {
            **chronology,
            "april_first_previous_governed_date": actual_previous,
            "march_to_april_calendar_link_pass": actual_previous == march_last,
        },
        "source_plan": {
            "source_names": list(plan["source_names"]),
            "cache_status": plan["cache_status"],
            "march_source": plan["march_source"],
            "march_ticker_days": int(plan["march_ticker_days"]),
            "march_minute_rows": int(plan["march_minute_rows"]),
            "full_ticker_days": int(plan["full_ticker_days"]),
            "full_minute_rows": int(plan["full_minute_rows"]),
        },
        "source_summaries": source_summaries,
        "semantic_capabilities": [
            "FORMATION_SEQUENCE_RUNS",
            "SEMANTIC_MARKERS_WITH_EXACT_TIME",
            "EVENT_JOURNEYS",
            "NO_FORCED_EVENT",
            "OPEN_RIGHT_CENSORED",
            "CROSS_DATE_CARRY",
            "FEB_MARCH_APRIL_CONTINUITY",
            "SOURCE_GAP_TIMING_UNCERTAINTY",
            "FAILED_RECOVERY_EVALUATION",
            "PULLBACK_RECLAIM_EVALUATION",
            "BUY_NONRESPONSE_WINDOWS",
            "SELL_RESILIENCE_WINDOWS",
            "OPEN_BREAK_RECLAIM",
            "EXPLICIT_UNKNOWN_UNPROVEN_AVAILABILITY",
        ],
        "manifest_sha256": None,
    }
    manifest["manifest_sha256"] = _digest_obj(
        {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    )
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    db.close()
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-root", required=True)
    p.add_argument(
        "--expected-v26-artifact-digest",
        default=BASELINE_V26_ARTIFACT_DIGEST,
    )
    a = p.parse_args()
    manifest = run(
        output_root=Path(a.output_root),
        expected_v26_artifact_digest=str(a.expected_v26_artifact_digest),
    )
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "status": manifest["status"],
                "reconciliation": manifest["reconciliation"],
                "chronology": manifest["chronology"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
