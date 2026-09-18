from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .haka_haki_reconstruction import DEC_2024_CONTRACT
from .v30_semantic_journey_enrichment import (
    SCHEMA as V30_SCHEMA,
    _digest_obj,
    _slug,
    _write_gz_jsonl,
    enrich_ticker_day,
)
from .v32_observation_envelope import (
    FULL_CHRONOLOGICAL_SOURCE_NAMES,
    ensure_full_observation_caches,
    iter_envelope_cached,
)

SCHEMA = "A1_V32_FULL_OBSERVATION_SEMANTIC_ENRICHMENT_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
V31_RUN_ID = 35291174908
V31_ARTIFACT_ID = 10533633559
V31_ARTIFACT_DIGEST = "sha256:b1f6b891aad38fa4afcdfd7e34657fb7b44456e96c8d2985d05f4f4378961f03"
V31_CORPUS_DIGEST = "9c2ed57ec60c81caaa0220ce57a7392473b2cf63eb23f8c846d4e961187e8732"


def _rewrite_v32(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["semantic_engine_parent_schema"] = V30_SCHEMA
    out["schema"] = SCHEMA
    out["lineage_version"] = "V3.2_FULL_OBSERVATION_ENVELOPE"
    return out


def _terminal_summary(bar: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        "timestamp": bar.get("timestamp"),
        "source_row": bar.get("source_row"),
        "source_phase": bar.get("source_phase"),
        "idx_regular_clock_session_code": bar.get("idx_regular_clock_session_code"),
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "trade_value": bar.get("trade_value"),
        "regular_behavior_eligible": bool(bar.get("regular_behavior_eligible")),
    }


def _phase_context_record(
    *,
    source: str,
    ticker: str,
    day: str,
    bar: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "source": source,
        "ticker": ticker,
        "date": day,
        "timestamp": bar.get("timestamp"),
        "source_row": bar.get("source_row"),
        "source_phase": bar.get("source_phase"),
        "idx_regular_clock_session_code": bar.get("idx_regular_clock_session_code"),
        "phase_flags": bar.get("phase_flags"),
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "trade_value": bar.get("trade_value"),
        "nbss": bar.get("nbss"),
        "flow_available": bool(bar.get("flow_available")),
        "mechanism_eligible": bool(bar.get("mechanism_eligible")),
        "regular_behavior_eligible": False,
        "role": "SOURCE_SUPPORTED_NONREGULAR_CONTEXT",
        "not_injected_into_regular_state_machine": True,
    }


def _build_day_index(
    db: sqlite3.Connection,
    source_summaries: list[Mapping[str, Any]],
) -> tuple[list[str], int, int, int]:
    db.execute("DROP TABLE IF EXISTS days")
    db.execute("DROP TABLE IF EXISTS calendar")
    db.execute(
        "CREATE TABLE days("
        "source_order INTEGER, source TEXT, ticker TEXT, day TEXT, "
        "source_observation_count INTEGER, regular_count INTEGER, "
        "first_timestamp TEXT, last_timestamp TEXT, terminal_close REAL, "
        "terminal_phase TEXT, terminal_session_code TEXT, terminal_source_row INTEGER, "
        "PRIMARY KEY(source,ticker,day))"
    )
    all_dates: set[str] = set()
    ticker_days = source_rows = regular_rows = 0
    for source_order, src in enumerate(source_summaries):
        source = str(src["source_name"])
        for packet in iter_envelope_cached(source):
            ticker = str(packet.get("ticker") or "")
            day = str(packet.get("date") or "")
            bars = [dict(x) for x in packet.get("bars", [])]
            if not ticker or not day:
                raise RuntimeError(f"V32_BAD_PACKET_IDENTITY:{source}:{ticker}:{day}")
            regular_count = sum(1 for x in bars if x.get("regular_behavior_eligible"))
            first = bars[0] if bars else None
            last = bars[-1] if bars else None
            db.execute(
                "INSERT INTO days VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_order,
                    source,
                    ticker,
                    day,
                    len(bars),
                    regular_count,
                    first.get("timestamp") if first else None,
                    last.get("timestamp") if last else None,
                    last.get("close") if last else None,
                    last.get("source_phase") if last else None,
                    str(last.get("idx_regular_clock_session_code")) if last else None,
                    int(last["source_row"]) if last and last.get("source_row") is not None else None,
                ),
            )
            all_dates.add(day)
            ticker_days += 1
            source_rows += len(bars)
            regular_rows += regular_count
    dates = sorted(all_dates)
    db.execute("CREATE TABLE calendar(day TEXT PRIMARY KEY, previous_day TEXT)")
    for i, day in enumerate(dates):
        db.execute(
            "INSERT INTO calendar VALUES(?,?)",
            (day, dates[i - 1] if i > 0 else None),
        )
    db.commit()
    return dates, ticker_days, source_rows, regular_rows


def _carry_for_full_observation(
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
        "SELECT source,source_observation_count,regular_count,first_timestamp,last_timestamp,"
        "terminal_close,terminal_phase,terminal_session_code,terminal_source_row "
        "FROM days WHERE ticker=? AND day=? ORDER BY source_order DESC LIMIT 1",
        (ticker, prev_day),
    ).fetchone()
    if prior is None:
        return {
            "status": "NO_TICKER_PACKET_ON_PREVIOUS_GOVERNED_DATE",
            "previous_governed_date": prev_day,
        }, prev_day
    if int(prior[1]) == 0:
        return {
            "status": "PREVIOUS_GOVERNED_DATE_HAS_NO_SOURCE_OBSERVATION",
            "previous_governed_date": prev_day,
            "source": prior[0],
            "regular_count": int(prior[2]),
        }, prev_day
    return {
        "status": "EXACT_PREVIOUS_GOVERNED_DATE_TERMINAL_SOURCE_OBSERVATION",
        "previous_governed_date": prev_day,
        "source": prior[0],
        "source_observation_count": int(prior[1]),
        "regular_count": int(prior[2]),
        "first_timestamp": prior[3],
        "last_timestamp": prior[4],
        "final_close": prior[5],
        "terminal_phase": prior[6],
        "terminal_session_code": prior[7],
        "terminal_source_row": prior[8],
        "carry_uses_source_envelope_not_last_regular_bar": True,
    }, prev_day


def _checkpoint_ok(path: Path, src: Mapping[str, Any], digest: str) -> bool:
    if not path.is_file():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        obj.get("schema") == SCHEMA
        and obj.get("status") == "PASS"
        and obj.get("envelope_digest_sha256") == digest
        and obj.get("source") == src.get("source_name")
        and int(obj.get("ticker_days", -1)) == int(src.get("ticker_days", -2))
        and int(obj.get("source_rows", -1)) == int(src.get("source_rows", -2))
        and int(obj.get("regular_rows", -1)) == int(src.get("regular_rows", -2))
    )


def run(*, output_root: Path) -> dict[str, Any]:
    catalog = ensure_full_observation_caches()
    if catalog["status"] != "PASS":
        raise RuntimeError("V32_ENVELOPE_CATALOG_NOT_PASS")
    if catalog["v31_corpus_digest_sha256"] != V31_CORPUS_DIGEST:
        raise RuntimeError("V32_V31_CORPUS_BINDING_MISMATCH")
    sources = list(catalog["sources"])
    if len(sources) != 18:
        raise RuntimeError(f"V32_SOURCE_COUNT_MISMATCH:{len(sources)}")
    envelope_digest = str(catalog["envelope_digest_sha256"])

    output_root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output_root / "day-index.sqlite3")
    dates, indexed_days, indexed_source_rows, indexed_regular_rows = _build_day_index(db, sources)
    if indexed_days != int(catalog["ticker_days"]):
        raise RuntimeError("V32_INDEX_TICKER_DAY_MISMATCH")
    if indexed_source_rows != int(catalog["source_rows"]):
        raise RuntimeError("V32_INDEX_SOURCE_ROW_MISMATCH")
    if indexed_regular_rows != int(catalog["regular_rows"]):
        raise RuntimeError("V32_INDEX_REGULAR_ROW_MISMATCH")

    totals = Counter()
    summaries: list[dict[str, Any]] = []
    sample: list[dict[str, Any]] = []
    reused_sources = 0

    for src in sources:
        source = str(src["source_name"])
        source_dir = output_root / _slug(source)
        source_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = source_dir / "checkpoint.json"
        if _checkpoint_ok(checkpoint, src, envelope_digest):
            cp = json.loads(checkpoint.read_text(encoding="utf-8"))
            summaries.append(cp)
            for key in (
                "ticker_days",
                "source_rows",
                "regular_rows",
                "nonregular_rows",
                "zero_regular_ticker_days",
                "zero_source_observation_ticker_days",
                "formation_runs",
                "semantic_markers",
                "event_journeys",
                "right_censored_journeys",
                "no_forced_event_ticker_days",
                "phase_context_records",
            ):
                totals[key] += int(cp.get(key, 0))
            reused_sources += 1
            continue

        td_path = source_dir / "ticker-days.jsonl.gz"
        runs_path = source_dir / "formation-runs.jsonl.gz"
        journeys_path = source_dir / "event-journeys.jsonl.gz"
        context_path = source_dir / "phase-context.jsonl.gz"
        td_tmp = td_path.with_suffix(td_path.suffix + ".tmp")
        runs_tmp = runs_path.with_suffix(runs_path.suffix + ".tmp")
        journeys_tmp = journeys_path.with_suffix(journeys_path.suffix + ".tmp")
        context_tmp = context_path.with_suffix(context_path.suffix + ".tmp")
        counts = Counter()
        allow_haka_haki = source == str(DEC_2024_CONTRACT["source_name"])

        with gzip.open(td_tmp, "wt", encoding="utf-8", newline="\n") as td_fh,              gzip.open(runs_tmp, "wt", encoding="utf-8", newline="\n") as runs_fh,              gzip.open(journeys_tmp, "wt", encoding="utf-8", newline="\n") as journeys_fh,              gzip.open(context_tmp, "wt", encoding="utf-8", newline="\n") as context_fh:
            for packet in iter_envelope_cached(source):
                ticker = str(packet.get("ticker") or "")
                day = str(packet.get("date") or "")
                envelope = [dict(x) for x in packet.get("bars", [])]
                regular = [x for x in envelope if x.get("regular_behavior_eligible")]
                nonregular = [x for x in envelope if not x.get("regular_behavior_eligible")]
                carry, prev_day = _carry_for_full_observation(db, ticker=ticker, day=day)
                td, runs, journeys = enrich_ticker_day(
                    regular,
                    source=source,
                    source_identity=src,
                    ticker=ticker,
                    trading_date=day,
                    carry_in=carry,
                    previous_governed_date=prev_day,
                    allow_haka_haki=allow_haka_haki,
                )
                td = _rewrite_v32(td)
                runs = [_rewrite_v32(dict(x)) for x in runs]
                journeys = [_rewrite_v32(dict(x)) for x in journeys]

                phases = Counter(str(x.get("source_phase")) for x in envelope)
                first_source = _terminal_summary(envelope[0] if envelope else None)
                last_source = _terminal_summary(envelope[-1] if envelope else None)
                td.update(
                    {
                        "source_observation_count": len(envelope),
                        "regular_bar_count": len(regular),
                        "nonregular_context_observation_count": len(nonregular),
                        "source_first_observation": first_source,
                        "source_terminal_observation": last_source,
                        "source_phase_counts": dict(sorted(phases.items())),
                        "regular_session_zero": len(regular) == 0,
                        "source_observation_zero": len(envelope) == 0,
                        "terminal_carry_uses_source_envelope": True,
                        "nonregular_context_not_injected_into_regular_state_machine": True,
                    }
                )

                td_fh.write(json.dumps(td, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                for rec in runs:
                    runs_fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                for rec in journeys:
                    journeys_fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                for bar in nonregular:
                    context_fh.write(
                        json.dumps(
                            _phase_context_record(source=source, ticker=ticker, day=day, bar=bar),
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        )
                        + "\n"
                    )

                counts["ticker_days"] += 1
                counts["source_rows"] += len(envelope)
                counts["regular_rows"] += len(regular)
                counts["nonregular_rows"] += len(nonregular)
                counts["zero_regular_ticker_days"] += int(not regular)
                counts["zero_source_observation_ticker_days"] += int(not envelope)
                counts["formation_runs"] += len(runs)
                counts["semantic_markers"] += int(td["semantic_marker_count"])
                counts["event_journeys"] += len(journeys)
                counts["right_censored_journeys"] += int(td["open_right_censored_journey_count"])
                counts["no_forced_event_ticker_days"] += int(td["no_forced_event"])
                counts["phase_context_records"] += len(nonregular)
                if len(sample) < 150:
                    sample.append(td)

        td_tmp.replace(td_path)
        runs_tmp.replace(runs_path)
        journeys_tmp.replace(journeys_path)
        context_tmp.replace(context_path)

        if counts["ticker_days"] != int(src["ticker_days"]):
            raise RuntimeError(f"V32_SOURCE_TICKER_DAY_FAIL:{source}:{dict(counts)}")
        if counts["source_rows"] != int(src["source_rows"]):
            raise RuntimeError(f"V32_SOURCE_OBSERVATION_FAIL:{source}:{dict(counts)}")
        if counts["regular_rows"] != int(src["regular_rows"]):
            raise RuntimeError(f"V32_SOURCE_REGULAR_FAIL:{source}:{dict(counts)}")
        if counts["nonregular_rows"] != int(src["nonregular_rows"]):
            raise RuntimeError(f"V32_SOURCE_NONREGULAR_FAIL:{source}:{dict(counts)}")

        cp = {
            "schema": SCHEMA,
            "status": "PASS",
            "research_status": STATUS,
            "envelope_digest_sha256": envelope_digest,
            "source": source,
            "source_drive_id": src.get("source_drive_id"),
            "source_sha256": src.get("source_sha256"),
            **{k: int(v) for k, v in counts.items()},
            "ticker_day_file": td_path.name,
            "formation_run_file": runs_path.name,
            "event_journey_file": journeys_path.name,
            "phase_context_file": context_path.name,
            "regular_state_engine_preserved": True,
            "nonregular_context_not_injected_into_regular_state_machine": True,
            "terminal_carry_uses_source_envelope": True,
            "v31_rewritten": False,
        }
        checkpoint.write_text(json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8")
        summaries.append(cp)
        totals.update(counts)

    if totals["ticker_days"] != int(catalog["ticker_days"]):
        raise RuntimeError(f"V32_GLOBAL_TICKER_DAY_FAIL:{dict(totals)}")
    if totals["source_rows"] != int(catalog["source_rows"]):
        raise RuntimeError(f"V32_GLOBAL_SOURCE_ROW_FAIL:{dict(totals)}")
    if totals["regular_rows"] != int(catalog["regular_rows"]):
        raise RuntimeError(f"V32_GLOBAL_REGULAR_ROW_FAIL:{dict(totals)}")
    if totals["nonregular_rows"] != int(catalog["nonregular_rows"]):
        raise RuntimeError(f"V32_GLOBAL_NONREGULAR_ROW_FAIL:{dict(totals)}")

    # Exact AALI concordance gates for the blind spot that opened V3.2.
    aali = {}
    for day in ("2024-12-02", "2024-12-03"):
        row = db.execute(
            "SELECT source_observation_count,regular_count,last_timestamp,terminal_close,"
            "terminal_phase,terminal_session_code FROM days WHERE ticker='AALI' AND day=?",
            (day,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"V32_AALI_CONCORDANCE_DAY_MISSING:{day}")
        aali[day] = {
            "source_observation_count": int(row[0]),
            "regular_count": int(row[1]),
            "last_timestamp": row[2],
            "terminal_close": row[3],
            "terminal_phase": row[4],
            "terminal_session_code": row[5],
        }
    if aali["2024-12-02"]["source_observation_count"] != 104:
        raise RuntimeError("V32_AALI_DEC2_SOURCE_COUNT_FAIL")
    if not str(aali["2024-12-02"]["last_timestamp"]).endswith("16:01:00"):
        raise RuntimeError("V32_AALI_DEC2_TERMINAL_TIME_FAIL")
    if float(aali["2024-12-02"]["terminal_close"]) != 6125.0:
        raise RuntimeError("V32_AALI_DEC2_TERMINAL_CLOSE_FAIL")
    if aali["2024-12-02"]["terminal_phase"] != "PRECLOSE_MATCH":
        raise RuntimeError("V32_AALI_DEC2_TERMINAL_PHASE_FAIL")
    if aali["2024-12-03"]["source_observation_count"] != 150:
        raise RuntimeError("V32_AALI_DEC3_SOURCE_COUNT_FAIL")
    if not str(aali["2024-12-03"]["last_timestamp"]).endswith("16:03:00"):
        raise RuntimeError("V32_AALI_DEC3_TERMINAL_TIME_FAIL")
    if float(aali["2024-12-03"]["terminal_close"]) != 6125.0:
        raise RuntimeError("V32_AALI_DEC3_TERMINAL_CLOSE_FAIL")

    carry_dec3, _ = _carry_for_full_observation(db, ticker="AALI", day="2024-12-03")
    if not carry_dec3 or float(carry_dec3.get("final_close") or 0) != 6125.0:
        raise RuntimeError("V32_AALI_DEC3_PRIOR_CARRY_FAIL")
    if not str(carry_dec3.get("last_timestamp") or "").endswith("16:01:00"):
        raise RuntimeError("V32_AALI_DEC3_PRIOR_CARRY_TIME_FAIL")

    sample_path = output_root / "compact-sample.jsonl.gz"
    _write_gz_jsonl(sample_path, sample)

    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "v31_baseline": {
            "run_id": V31_RUN_ID,
            "artifact_id": V31_ARTIFACT_ID,
            "artifact_digest": V31_ARTIFACT_DIGEST,
            "corpus_digest_sha256": V31_CORPUS_DIGEST,
            "preserved_immutable": True,
        },
        "envelope_digest_sha256": envelope_digest,
        "contract": {
            "full_source_supported_observation_envelope_preserved": True,
            "phase_from_source_flags_not_clock_inference": True,
            "regular_state_engine_preserved": True,
            "nonregular_context_not_injected_into_regular_state_machine": True,
            "cross_date_carry_uses_terminal_source_observation": True,
            "manual_labels_not_used_as_hidden_targets": True,
            "v31_not_rewritten": True,
            "v2x_not_rewritten": True,
            "missing_unproven_not_zero": True,
            "causal_view_separate_from_hindsight": True,
        },
        "reconciliation": {
            "pass": True,
            "source_count": len(sources),
            "ticker_days": int(totals["ticker_days"]),
            "source_rows": int(totals["source_rows"]),
            "regular_rows": int(totals["regular_rows"]),
            "nonregular_rows": int(totals["nonregular_rows"]),
            "zero_regular_ticker_days": int(totals["zero_regular_ticker_days"]),
            "zero_source_observation_ticker_days": int(totals["zero_source_observation_ticker_days"]),
            "formation_runs": int(totals["formation_runs"]),
            "semantic_markers": int(totals["semantic_markers"]),
            "event_journeys": int(totals["event_journeys"]),
            "right_censored_journeys": int(totals["right_censored_journeys"]),
            "no_forced_event_ticker_days": int(totals["no_forced_event_ticker_days"]),
            "phase_context_records": int(totals["phase_context_records"]),
            "governed_dates": len(dates),
            "reused_pass_sources": reused_sources,
        },
        "aali_concordance_gate": {
            "pass": True,
            "dec2": aali["2024-12-02"],
            "dec3": aali["2024-12-03"],
            "dec3_prior_carry": carry_dec3,
        },
        "source_summaries": summaries,
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
    a = p.parse_args()
    manifest = run(output_root=Path(a.output_root))
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "status": manifest["status"],
                "reconciliation": manifest["reconciliation"],
                "aali_concordance_gate": manifest["aali_concordance_gate"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
