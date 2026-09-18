from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
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
from .v32_behavior_lifecycle import (
    LIFECYCLE_TIMING_FIELDS,
    SCHEMA as V32_LIFECYCLE_SCHEMA,
    enrich_behavior_lifecycle,
)
from .v32_observation_envelope import (
    FULL_CHRONOLOGICAL_SOURCE_NAMES,
    ensure_full_observation_caches,
    iter_envelope_cached,
)

SCHEMA = "A1_V32_FULL_OBSERVATION_SEMANTIC_ENRICHMENT_V3"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
V31_RUN_ID = 35291174908
V31_ARTIFACT_ID = 10533633559
V31_ARTIFACT_DIGEST = "sha256:b1f6b891aad38fa4afcdfd7e34657fb7b44456e96c8d2985d05f4f4378961f03"
V31_CORPUS_DIGEST = "9c2ed57ec60c81caaa0220ce57a7392473b2cf63eb23f8c846d4e961187e8732"


def _rewrite_v32(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["semantic_engine_parent_schema"] = V30_SCHEMA
    out["schema"] = SCHEMA
    out["lineage_version"] = "V3.2_FULL_OBSERVATION_AND_BEHAVIOR_CAPABILITY"
    return out


def _software_revision() -> str:
    value = os.environ.get("A1_V32_SOFTWARE_REVISION", "").strip()
    if not value:
        raise RuntimeError("V32_SOFTWARE_REVISION_REQUIRED")
    return value


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _terminal_summary(bar: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if bar is None:
        return None
    return {
        "timestamp": bar.get("timestamp"),
        "known_at": bar.get("timestamp"),
        "source_row": bar.get("source_row"),
        "source_phase": bar.get("source_phase"),
        "observation_role": bar.get("observation_role"),
        "idx_clock_ruleset_code": bar.get("idx_clock_ruleset_code"),
        "idx_regular_clock_session_code": bar.get("idx_regular_clock_session_code"),
        "phase_flags": bar.get("phase_flags"),
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "trade_value": bar.get("trade_value"),
        "nbss": bar.get("nbss"),
        "flow_available": bar.get("flow_available"),
        "mechanism_eligible": bar.get("mechanism_eligible"),
        "session_eligible": bar.get("session_eligible"),
        "regular_behavior_eligible": bar.get("regular_behavior_eligible"),
        "haka": bar.get("haka"),
        "haki": bar.get("haki"),
        "haka_haki_status": bar.get("haka_haki_status"),
    }


def _closing_match_summary(bars: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    matches = [
        bar
        for bar in bars
        if bar.get("source_phase") == "PRECLOSE_MATCH"
        or bool((bar.get("phase_flags") or {}).get("CLK_PRECLOSE_MATCH_FLAG"))
    ]
    if not matches:
        return None
    return {
        "observation_count": len(matches),
        "first": _terminal_summary(matches[0]),
        "last": _terminal_summary(matches[-1]),
    }


def _journey_carry_payload(journeys: list[Mapping[str, Any]]) -> dict[str, Any]:
    open_rows = []
    for row in journeys:
        resolution = dict(row.get("hindsight_resolution") or {})
        if not bool(resolution.get("right_censored")):
            continue
        open_rows.append(
            {
                "journey_kind": row.get("journey_kind"),
                "causal_start": row.get("causal_start"),
                "hindsight_resolution": resolution,
            }
        )
    return {
        "status": "OPEN_RIGHT_CENSORED_PRESENT" if open_rows else "NO_OPEN_RIGHT_CENSORED_JOURNEY",
        "open_right_censored_count": len(open_rows),
        "journeys": open_rows,
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
        "known_at": bar.get("timestamp"),
        "source_row": bar.get("source_row"),
        "source_phase": bar.get("source_phase"),
        "observation_role": bar.get("observation_role"),
        "idx_clock_ruleset_code": bar.get("idx_clock_ruleset_code"),
        "idx_regular_clock_session_code": bar.get("idx_regular_clock_session_code"),
        "phase_flags": bar.get("phase_flags"),
        "open": bar.get("open"),
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "trade_value": bar.get("trade_value"),
        "nbss": bar.get("nbss"),
        "flow_available": bar.get("flow_available"),
        "mechanism_eligible": bar.get("mechanism_eligible"),
        "session_eligible": bar.get("session_eligible"),
        "regular_behavior_eligible": False,
        "haka": bar.get("haka"),
        "haki": bar.get("haki"),
        "haka_haki_status": bar.get("haka_haki_status"),
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
        "source_order INTEGER, source TEXT, source_drive_id TEXT, source_sha256 TEXT, generation_id TEXT, "
        "ticker TEXT, day TEXT, source_observation_count INTEGER, regular_count INTEGER, "
        "first_timestamp TEXT, last_timestamp TEXT, last_regular_state_json TEXT, "
        "last_source_state_json TEXT, closing_match_state_json TEXT, "
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
            regular = [x for x in bars if x.get("regular_behavior_eligible")]
            first = bars[0] if bars else None
            last = bars[-1] if bars else None
            last_regular = regular[-1] if regular else None
            last_regular_state = _terminal_summary(last_regular)
            last_source_state = _terminal_summary(last)
            closing_match_state = _closing_match_summary(bars)
            db.execute(
                "INSERT INTO days VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_order,
                    source,
                    str(src.get("source_drive_id") or ""),
                    str(src.get("source_sha256") or ""),
                    str(src.get("generation_id") or ""),
                    ticker,
                    day,
                    len(bars),
                    len(regular),
                    first.get("timestamp") if first else None,
                    last.get("timestamp") if last else None,
                    json.dumps(last_regular_state, sort_keys=True, separators=(",", ":")) if last_regular_state is not None else None,
                    json.dumps(last_source_state, sort_keys=True, separators=(",", ":")) if last_source_state is not None else None,
                    json.dumps(closing_match_state, sort_keys=True, separators=(",", ":")) if closing_match_state is not None else None,
                ),
            )
            all_dates.add(day)
            ticker_days += 1
            source_rows += len(bars)
            regular_rows += len(regular)
    dates = sorted(all_dates)
    db.execute("CREATE TABLE calendar(day TEXT PRIMARY KEY, previous_day TEXT)")
    for i, day in enumerate(dates):
        db.execute(
            "INSERT INTO calendar VALUES(?,?)",
            (day, dates[i - 1] if i > 0 else None),
        )
    db.commit()
    return dates, ticker_days, source_rows, regular_rows


def _init_journey_carry(db: sqlite3.Connection) -> None:
    db.execute("DROP TABLE IF EXISTS journey_carry")
    db.execute(
        "CREATE TABLE journey_carry("
        "ticker TEXT, day TEXT, open_state_json TEXT NOT NULL, "
        "PRIMARY KEY(ticker,day))"
    )
    db.commit()


def _store_journey_carry(
    db: sqlite3.Connection,
    *,
    ticker: str,
    day: str,
    journeys: list[Mapping[str, Any]],
) -> None:
    payload = _journey_carry_payload(journeys)
    db.execute(
        "INSERT OR REPLACE INTO journey_carry VALUES(?,?,?)",
        (
            ticker,
            day,
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        ),
    )


def _restore_journey_carry(db: sqlite3.Connection, source_dir: Path) -> None:
    ticker_day_path = source_dir / "ticker-days.jsonl.gz"
    journeys_path = source_dir / "event-journeys.jsonl.gz"
    if not ticker_day_path.is_file() or not journeys_path.is_file():
        raise RuntimeError(f"V32_REUSED_SOURCE_CARRY_FILES_MISSING:{source_dir}")
    states: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with gzip.open(ticker_day_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            key = (str(row.get("ticker") or ""), str(row.get("date") or ""))
            if not all(key):
                raise RuntimeError("V32_REUSED_TICKER_DAY_IDENTITY_MISSING")
            states.setdefault(key, [])
    with gzip.open(journeys_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            resolution = dict(row.get("hindsight_resolution") or {})
            if not bool(resolution.get("right_censored")):
                continue
            key = (str(row.get("ticker") or ""), str(row.get("date") or ""))
            if key not in states:
                raise RuntimeError(f"V32_REUSED_JOURNEY_WITHOUT_TICKER_DAY:{key}")
            states[key].append(row)
    for (ticker, day), journeys in states.items():
        _store_journey_carry(db, ticker=ticker, day=day, journeys=journeys)
    db.commit()


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
        "SELECT source,source_drive_id,source_sha256,generation_id,"
        "source_observation_count,regular_count,first_timestamp,last_timestamp,"
        "last_regular_state_json,last_source_state_json,closing_match_state_json "
        "FROM days WHERE ticker=? AND day=? ORDER BY source_order DESC LIMIT 1",
        (ticker, prev_day),
    ).fetchone()
    if prior is None:
        return {
            "status": "NO_TICKER_PACKET_ON_PREVIOUS_GOVERNED_DATE",
            "previous_governed_date": prev_day,
        }, prev_day
    if int(prior[4]) == 0:
        return {
            "status": "PREVIOUS_GOVERNED_DATE_HAS_NO_SOURCE_OBSERVATION",
            "previous_governed_date": prev_day,
            "source": prior[0],
            "regular_count": int(prior[5]),
            "provenance": {
                "source_drive_id": prior[1],
                "source_sha256": prior[2],
                "generation_id": prior[3],
            },
        }, prev_day

    last_regular = json.loads(prior[8]) if prior[8] else None
    last_source = json.loads(prior[9]) if prior[9] else None
    closing_match = json.loads(prior[10]) if prior[10] else None
    if last_source is None:
        raise RuntimeError(f"V32_PRIOR_LAST_SOURCE_STATE_MISSING:{ticker}:{prev_day}")
    journey_row = db.execute(
        "SELECT open_state_json FROM journey_carry WHERE ticker=? AND day=?",
        (ticker, prev_day),
    ).fetchone()
    if journey_row is None:
        raise RuntimeError(f"V32_PRIOR_JOURNEY_CARRY_NOT_READY:{ticker}:{prev_day}")
    journey_state = json.loads(journey_row[0])
    availability = {
        "flow_available": last_source.get("flow_available"),
        "mechanism_eligible": last_source.get("mechanism_eligible"),
        "session_eligible": last_source.get("session_eligible"),
        "haka_haki_status": last_source.get("haka_haki_status"),
    }
    return {
        "status": "EXACT_PREVIOUS_GOVERNED_DATE_SOURCE_SUPPORTED_CARRY",
        "previous_governed_date": prev_day,
        "source": prior[0],
        "source_observation_count": int(prior[4]),
        "regular_count": int(prior[5]),
        "first_timestamp": prior[6],
        "last_timestamp": prior[7],
        "last_regular_session_state": last_regular,
        "last_source_supported_observation_state": last_source,
        "previous_terminal_observation_phase": last_source.get("source_phase"),
        "closing_preclose_match_state": closing_match,
        "prior_event_journey_open_right_censored_state": journey_state,
        "provenance": {
            "source_drive_id": prior[1],
            "source_sha256": prior[2],
            "generation_id": prior[3],
            "terminal_source_row": last_source.get("source_row"),
        },
        "availability": availability,
        "known_at_boundary": last_source.get("timestamp"),
        "carry_uses_source_envelope_not_last_regular_bar": True,
    }, prev_day


def _checkpoint_ok(path: Path, src: Mapping[str, Any], digest: str, software_revision: str) -> bool:
    if not path.is_file():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    base_ok = (
        obj.get("schema") == SCHEMA
        and obj.get("status") == "PASS"
        and obj.get("envelope_digest_sha256") == digest
        and obj.get("source") == src.get("source_name")
        and obj.get("software_revision") == software_revision
        and int(obj.get("ticker_days", -1)) == int(src.get("ticker_days", -2))
        and int(obj.get("source_rows", -1)) == int(src.get("source_rows", -2))
        and int(obj.get("regular_rows", -1)) == int(src.get("regular_rows", -2))
    )
    if not base_ok:
        return False
    outputs = obj.get("output_files")
    if not isinstance(outputs, dict):
        return False
    required = {
        "ticker_days",
        "formation_runs",
        "event_journeys",
        "phase_context",
        "full_observation_envelope",
        "regular_behavior_stream",
        "behavior_day_profiles",
        "behavior_lifecycle",
        "behavior_paths",
    }
    if not required.issubset(outputs):
        return False
    for key in sorted(required):
        meta = outputs.get(key)
        if not isinstance(meta, dict):
            return False
        name = str(meta.get("name") or "")
        expected_sha = str(meta.get("sha256") or "")
        expected_bytes = int(meta.get("bytes") or -1)
        artifact = path.parent / name
        if not name or not expected_sha or not artifact.is_file():
            return False
        if artifact.stat().st_size != expected_bytes:
            return False
        if _sha256_file(artifact) != expected_sha:
            return False
    return True


def run(*, output_root: Path) -> dict[str, Any]:
    software_revision = _software_revision()
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
    _init_journey_carry(db)

    totals = Counter()
    summaries: list[dict[str, Any]] = []
    sample: list[dict[str, Any]] = []
    reused_sources = 0

    for src in sources:
        source = str(src["source_name"])
        source_dir = output_root / _slug(source)
        source_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = source_dir / "checkpoint.json"
        if _checkpoint_ok(checkpoint, src, envelope_digest, software_revision):
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
                "behavior_day_profiles",
                "behavior_lifecycle_journeys",
                "behavior_lifecycle_open_journeys",
                "behavior_lifecycle_contract_records",
                "behavior_paths",
                "behavior_state_transitions",
            ):
                totals[key] += int(cp.get(key, 0))
            _restore_journey_carry(db, source_dir)
            reused_sources += 1
            continue

        td_path = source_dir / "ticker-days.jsonl.gz"
        runs_path = source_dir / "formation-runs.jsonl.gz"
        journeys_path = source_dir / "event-journeys.jsonl.gz"
        context_path = source_dir / "phase-context.jsonl.gz"
        full_layer_path = source_dir / "full-observation-envelope.jsonl.gz"
        regular_layer_path = source_dir / "regular-behavior-stream.jsonl.gz"
        behavior_day_path = source_dir / "behavior-day-profiles.jsonl.gz"
        behavior_lifecycle_path = source_dir / "behavior-lifecycle.jsonl.gz"
        behavior_path_path = source_dir / "behavior-paths.jsonl.gz"
        td_tmp = td_path.with_suffix(td_path.suffix + ".tmp")
        runs_tmp = runs_path.with_suffix(runs_path.suffix + ".tmp")
        journeys_tmp = journeys_path.with_suffix(journeys_path.suffix + ".tmp")
        context_tmp = context_path.with_suffix(context_path.suffix + ".tmp")
        full_layer_tmp = full_layer_path.with_suffix(full_layer_path.suffix + ".tmp")
        regular_layer_tmp = regular_layer_path.with_suffix(regular_layer_path.suffix + ".tmp")
        behavior_day_tmp = behavior_day_path.with_suffix(behavior_day_path.suffix + ".tmp")
        behavior_lifecycle_tmp = behavior_lifecycle_path.with_suffix(behavior_lifecycle_path.suffix + ".tmp")
        behavior_path_tmp = behavior_path_path.with_suffix(behavior_path_path.suffix + ".tmp")
        counts = Counter()
        allow_haka_haki = source == str(DEC_2024_CONTRACT["source_name"])

        with gzip.open(td_tmp, "wt", encoding="utf-8", newline="\n") as td_fh,              gzip.open(runs_tmp, "wt", encoding="utf-8", newline="\n") as runs_fh,              gzip.open(journeys_tmp, "wt", encoding="utf-8", newline="\n") as journeys_fh,              gzip.open(context_tmp, "wt", encoding="utf-8", newline="\n") as context_fh,              gzip.open(full_layer_tmp, "wt", encoding="utf-8", newline="\n") as full_layer_fh,              gzip.open(regular_layer_tmp, "wt", encoding="utf-8", newline="\n") as regular_layer_fh,              gzip.open(behavior_day_tmp, "wt", encoding="utf-8", newline="\n") as behavior_day_fh,              gzip.open(behavior_lifecycle_tmp, "wt", encoding="utf-8", newline="\n") as behavior_lifecycle_fh,              gzip.open(behavior_path_tmp, "wt", encoding="utf-8", newline="\n") as behavior_path_fh:
            for packet in iter_envelope_cached(source):
                ticker = str(packet.get("ticker") or "")
                day = str(packet.get("date") or "")
                envelope = [dict(x) for x in packet.get("bars", [])]
                source_header = list(packet.get("source_header") or [])
                source_packet_fingerprint = packet.get("source_packet_fingerprint")
                if packet.get("all_source_columns_retained") is not True:
                    raise RuntimeError(f"V32_SOURCE_COLUMNS_NOT_RETAINED:{source}:{ticker}:{day}")
                if not source_header:
                    raise RuntimeError(f"V32_SOURCE_HEADER_EMPTY:{source}:{ticker}:{day}")
                for i, bar in enumerate(envelope):
                    values = bar.get("source_field_values")
                    if not isinstance(values, list) or len(values) != len(source_header):
                        raise RuntimeError(
                            f"V32_SOURCE_FIELD_RETRIEVAL_MISMATCH:{source}:{ticker}:{day}:{i}"
                        )
                regular = [x for x in envelope if x.get("regular_behavior_eligible")]
                nonregular = [x for x in envelope if not x.get("regular_behavior_eligible")]
                layer_identity = {
                    "schema": SCHEMA,
                    "source": source,
                    "source_drive_id": src.get("source_drive_id"),
                    "source_sha256": src.get("source_sha256"),
                    "generation_id": src.get("generation_id"),
                    "ticker": ticker,
                    "date": day,
                }
                full_layer_fh.write(
                    json.dumps(
                        {
                            **layer_identity,
                            "layer": "FULL_OBSERVATION_ENVELOPE",
                            "source_header": source_header,
                            "source_header_field_count": len(source_header),
                            "source_packet_fingerprint": source_packet_fingerprint,
                            "all_source_columns_retained": True,
                            "bars": envelope,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                regular_layer_fh.write(
                    json.dumps(
                        {
                            **layer_identity,
                            "layer": "REGULAR_BEHAVIOR_STREAM",
                            "source_header": source_header,
                            "source_header_field_count": len(source_header),
                            "source_packet_fingerprint": source_packet_fingerprint,
                            "all_source_columns_retained_upstream": True,
                            "bars": regular,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                    + "\n"
                )
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
                behavior_day, lifecycle_records, behavior_path = enrich_behavior_lifecycle(
                    bars=regular,
                    full_envelope=envelope,
                    runs=runs,
                    journeys=journeys,
                    source=source,
                    ticker=ticker,
                    trading_date=day,
                    carry_in=carry,
                )
                if len(lifecycle_records) != len(journeys):
                    raise RuntimeError(f"V32_LIFECYCLE_JOURNEY_COVERAGE_FAIL:{source}:{ticker}:{day}")
                behavior_day_fh.write(json.dumps(behavior_day, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                for rec in lifecycle_records:
                    behavior_lifecycle_fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                behavior_path_fh.write(json.dumps(behavior_path, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                _store_journey_carry(db, ticker=ticker, day=day, journeys=journeys)

                phases = Counter(str(x.get("source_phase")) for x in envelope)
                first_source = _terminal_summary(envelope[0] if envelope else None)
                last_regular = _terminal_summary(regular[-1] if regular else None)
                last_source = _terminal_summary(envelope[-1] if envelope else None)
                closing_match = _closing_match_summary(envelope)
                td.update(
                    {
                        "source_observation_count": len(envelope),
                        "regular_bar_count": len(regular),
                        "nonregular_context_observation_count": len(nonregular),
                        "source_first_observation": first_source,
                        "source_terminal_observation": last_source,
                        "last_regular_session_state": last_regular,
                        "last_source_supported_observation_state": last_source,
                        "closing_preclose_match_state": closing_match,
                        "source_phase_counts": dict(sorted(phases.items())),
                        "regular_session_zero": len(regular) == 0,
                        "source_observation_zero": len(envelope) == 0,
                        "terminal_carry_uses_source_envelope": True,
                        "nonregular_context_not_injected_into_regular_state_machine": True,
                        "behavior_lifecycle_schema": V32_LIFECYCLE_SCHEMA,
                        "behavior_lifecycle_journey_count": len(lifecycle_records),
                        "behavior_lifecycle_open_journey_count": int(behavior_day["open_right_censored_journey_count"]),
                        "behavior_lifecycle_contract": behavior_day["lifecycle_contract"],
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
                counts["behavior_day_profiles"] += 1
                counts["behavior_lifecycle_journeys"] += len(lifecycle_records)
                counts["behavior_lifecycle_open_journeys"] += int(behavior_day["open_right_censored_journey_count"])
                counts["behavior_lifecycle_contract_records"] += sum(int(bool(x.get("timing_contract_complete"))) for x in lifecycle_records)
                counts["behavior_paths"] += 1
                counts["behavior_state_transitions"] += int(behavior_path["state_transition_count"])
                if len(sample) < 150:
                    sample.append(td)

        td_tmp.replace(td_path)
        runs_tmp.replace(runs_path)
        journeys_tmp.replace(journeys_path)
        context_tmp.replace(context_path)
        full_layer_tmp.replace(full_layer_path)
        regular_layer_tmp.replace(regular_layer_path)
        behavior_day_tmp.replace(behavior_day_path)
        behavior_lifecycle_tmp.replace(behavior_lifecycle_path)
        behavior_path_tmp.replace(behavior_path_path)
        db.commit()

        if counts["ticker_days"] != int(src["ticker_days"]):
            raise RuntimeError(f"V32_SOURCE_TICKER_DAY_FAIL:{source}:{dict(counts)}")
        if counts["source_rows"] != int(src["source_rows"]):
            raise RuntimeError(f"V32_SOURCE_OBSERVATION_FAIL:{source}:{dict(counts)}")
        if counts["regular_rows"] != int(src["regular_rows"]):
            raise RuntimeError(f"V32_SOURCE_REGULAR_FAIL:{source}:{dict(counts)}")
        if counts["nonregular_rows"] != int(src["nonregular_rows"]):
            raise RuntimeError(f"V32_SOURCE_NONREGULAR_FAIL:{source}:{dict(counts)}")
        if counts["source_rows"] != counts["regular_rows"] + counts["nonregular_rows"]:
            raise RuntimeError(f"V32_SOURCE_LAYER_ACCOUNTING_FAIL:{source}:{dict(counts)}")
        if counts["behavior_day_profiles"] != counts["ticker_days"]:
            raise RuntimeError(f"V32_SOURCE_BEHAVIOR_DAY_COVERAGE_FAIL:{source}:{dict(counts)}")
        if counts["behavior_lifecycle_journeys"] != counts["event_journeys"]:
            raise RuntimeError(f"V32_SOURCE_LIFECYCLE_JOURNEY_COVERAGE_FAIL:{source}:{dict(counts)}")
        if counts["behavior_lifecycle_contract_records"] != counts["behavior_lifecycle_journeys"]:
            raise RuntimeError(f"V32_SOURCE_LIFECYCLE_CONTRACT_FAIL:{source}:{dict(counts)}")
        if counts["behavior_paths"] != counts["ticker_days"]:
            raise RuntimeError(f"V32_SOURCE_BEHAVIOR_PATH_COVERAGE_FAIL:{source}:{dict(counts)}")

        output_files = {
            "ticker_days": {
                "name": td_path.name,
                "sha256": _sha256_file(td_path),
                "bytes": td_path.stat().st_size,
            },
            "formation_runs": {
                "name": runs_path.name,
                "sha256": _sha256_file(runs_path),
                "bytes": runs_path.stat().st_size,
            },
            "event_journeys": {
                "name": journeys_path.name,
                "sha256": _sha256_file(journeys_path),
                "bytes": journeys_path.stat().st_size,
            },
            "phase_context": {
                "name": context_path.name,
                "sha256": _sha256_file(context_path),
                "bytes": context_path.stat().st_size,
            },
            "full_observation_envelope": {
                "name": full_layer_path.name,
                "sha256": _sha256_file(full_layer_path),
                "bytes": full_layer_path.stat().st_size,
            },
            "regular_behavior_stream": {
                "name": regular_layer_path.name,
                "sha256": _sha256_file(regular_layer_path),
                "bytes": regular_layer_path.stat().st_size,
            },
            "behavior_day_profiles": {
                "name": behavior_day_path.name,
                "sha256": _sha256_file(behavior_day_path),
                "bytes": behavior_day_path.stat().st_size,
            },
            "behavior_lifecycle": {
                "name": behavior_lifecycle_path.name,
                "sha256": _sha256_file(behavior_lifecycle_path),
                "bytes": behavior_lifecycle_path.stat().st_size,
            },
            "behavior_paths": {
                "name": behavior_path_path.name,
                "sha256": _sha256_file(behavior_path_path),
                "bytes": behavior_path_path.stat().st_size,
            },
        }

        cp = {
            "schema": SCHEMA,
            "status": "PASS",
            "research_status": STATUS,
            "envelope_digest_sha256": envelope_digest,
            "source": source,
            "software_revision": software_revision,
            "source_drive_id": src.get("source_drive_id"),
            "source_sha256": src.get("source_sha256"),
            **{k: int(v) for k, v in counts.items()},
            "ticker_day_file": td_path.name,
            "formation_run_file": runs_path.name,
            "event_journey_file": journeys_path.name,
            "phase_context_file": context_path.name,
            "full_observation_layer_file": full_layer_path.name,
            "regular_behavior_stream_file": regular_layer_path.name,
            "behavior_day_profile_file": behavior_day_path.name,
            "behavior_lifecycle_file": behavior_lifecycle_path.name,
            "behavior_path_file": behavior_path_path.name,
            "output_files": output_files,
            "full_observation_rows": int(counts["source_rows"]),
            "regular_behavior_rows": int(counts["regular_rows"]),
            "nonregular_observation_rows": int(counts["nonregular_rows"]),
            "excluded_rows": 0,
            "exclusion_reasons": {},
            "dual_layer_materialized": True,
            "all_source_columns_retrievable": True,
            "source_values_retained_for_every_observation": True,
            "source_packet_fingerprint_preserved": True,
            "regular_state_engine_preserved": True,
            "nonregular_context_not_injected_into_regular_state_machine": True,
            "terminal_carry_uses_source_envelope": True,
            "manual_behavior_lifecycle_contract_materialized": True,
            "all_event_journeys_have_lifecycle_representation": True,
            "observation_only_days_preserved": True,
            "unnamed_state_transitions_preserved": True,
            "all_machine_state_changes_preserved_without_event_label": True,
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
    if totals["source_rows"] != totals["regular_rows"] + totals["nonregular_rows"]:
        raise RuntimeError(f"V32_GLOBAL_LAYER_ACCOUNTING_FAIL:{dict(totals)}")
    if totals["behavior_day_profiles"] != totals["ticker_days"]:
        raise RuntimeError(f"V32_GLOBAL_BEHAVIOR_DAY_COVERAGE_FAIL:{dict(totals)}")
    if totals["behavior_lifecycle_journeys"] != totals["event_journeys"]:
        raise RuntimeError(f"V32_GLOBAL_LIFECYCLE_JOURNEY_COVERAGE_FAIL:{dict(totals)}")
    if totals["behavior_lifecycle_contract_records"] != totals["behavior_lifecycle_journeys"]:
        raise RuntimeError(f"V32_GLOBAL_LIFECYCLE_CONTRACT_FAIL:{dict(totals)}")
    if totals["behavior_paths"] != totals["ticker_days"]:
        raise RuntimeError(f"V32_GLOBAL_BEHAVIOR_PATH_COVERAGE_FAIL:{dict(totals)}")

    # Exact AALI concordance gates for the blind spot that opened V3.2.
    aali = {}
    for day in ("2024-12-02", "2024-12-03"):
        row = db.execute(
            "SELECT source_observation_count,regular_count,last_regular_state_json,"
            "last_source_state_json,closing_match_state_json "
            "FROM days WHERE ticker='AALI' AND day=?",
            (day,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"V32_AALI_CONCORDANCE_DAY_MISSING:{day}")
        aali[day] = {
            "source_observation_count": int(row[0]),
            "regular_count": int(row[1]),
            "last_regular_session_state": json.loads(row[2]) if row[2] else None,
            "last_source_supported_observation_state": json.loads(row[3]) if row[3] else None,
            "closing_preclose_match_state": json.loads(row[4]) if row[4] else None,
        }

    dec2_regular = aali["2024-12-02"]["last_regular_session_state"] or {}
    dec2_source = aali["2024-12-02"]["last_source_supported_observation_state"] or {}
    dec3_source = aali["2024-12-03"]["last_source_supported_observation_state"] or {}
    if aali["2024-12-02"]["source_observation_count"] != 104:
        raise RuntimeError("V32_AALI_DEC2_SOURCE_COUNT_FAIL")
    if aali["2024-12-02"]["regular_count"] != 102:
        raise RuntimeError("V32_AALI_DEC2_REGULAR_COUNT_FAIL")
    if not str(dec2_regular.get("timestamp") or "").endswith("15:49:00"):
        raise RuntimeError("V32_AALI_DEC2_LAST_REGULAR_TIME_FAIL")
    if float(dec2_regular.get("close") or 0) != 6175.0:
        raise RuntimeError("V32_AALI_DEC2_LAST_REGULAR_CLOSE_FAIL")
    if not str(dec2_source.get("timestamp") or "").endswith("16:01:00"):
        raise RuntimeError("V32_AALI_DEC2_TERMINAL_TIME_FAIL")
    if float(dec2_source.get("close") or 0) != 6125.0:
        raise RuntimeError("V32_AALI_DEC2_TERMINAL_CLOSE_FAIL")
    if dec2_source.get("source_phase") != "PRECLOSE_MATCH":
        raise RuntimeError("V32_AALI_DEC2_TERMINAL_PHASE_FAIL")
    if aali["2024-12-03"]["source_observation_count"] != 150:
        raise RuntimeError("V32_AALI_DEC3_SOURCE_COUNT_FAIL")
    if not str(dec3_source.get("timestamp") or "").endswith("16:03:00"):
        raise RuntimeError("V32_AALI_DEC3_TERMINAL_TIME_FAIL")
    if float(dec3_source.get("close") or 0) != 6125.0:
        raise RuntimeError("V32_AALI_DEC3_TERMINAL_CLOSE_FAIL")

    carry_dec3, _ = _carry_for_full_observation(db, ticker="AALI", day="2024-12-03")
    carry_dec2_source = dict((carry_dec3 or {}).get("last_source_supported_observation_state") or {})
    carry_dec2_regular = dict((carry_dec3 or {}).get("last_regular_session_state") or {})
    if float(carry_dec2_source.get("close") or 0) != 6125.0:
        raise RuntimeError("V32_AALI_DEC3_PRIOR_CARRY_FAIL")
    if not str(carry_dec2_source.get("timestamp") or "").endswith("16:01:00"):
        raise RuntimeError("V32_AALI_DEC3_PRIOR_CARRY_TIME_FAIL")
    if float(carry_dec2_regular.get("close") or 0) != 6175.0:
        raise RuntimeError("V32_AALI_DEC3_PRIOR_REGULAR_CARRY_FAIL")
    if (carry_dec3 or {}).get("known_at_boundary") != carry_dec2_source.get("timestamp"):
        raise RuntimeError("V32_AALI_DEC3_KNOWN_AT_BOUNDARY_FAIL")

    sample_path = output_root / "compact-sample.jsonl.gz"
    _write_gz_jsonl(sample_path, sample)

    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "software_revision": software_revision,
        "behavior_lifecycle_schema": V32_LIFECYCLE_SCHEMA,
        "behavior_lifecycle_timing_fields": list(LIFECYCLE_TIMING_FIELDS),
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
            "all_source_columns_retrievable_from_full_observation_layer": True,
            "source_values_retained_for_every_observation": True,
            "source_packet_fingerprint_preserved": True,
            "manual_benchmark_evidence_retrievability_supported": True,
            "semantic_interpretation_independence_preserved": True,
            "full_layer_has_source_file_hash_generation_row_time_and_all_field_values": True,
            "phase_from_source_flags_not_clock_inference": True,
            "regular_state_engine_preserved": True,
            "nonregular_context_not_injected_into_regular_state_machine": True,
            "cross_date_carry_uses_terminal_source_observation": True,
            "last_regular_and_last_source_supported_states_separated": True,
            "closing_preclose_match_state_preserved": True,
            "prior_open_right_censored_journey_state_preserved_in_carry": True,
            "dual_layer_materialized_per_ticker_day": True,
            "manual_labels_not_used_as_hidden_targets": True,
            "v31_not_rewritten": True,
            "v2x_not_rewritten": True,
            "missing_unproven_not_zero": True,
            "causal_view_separate_from_hindsight": True,
            "manual_behavior_lifecycle_contract_materialized": True,
            "prior_condition_preserved": True,
            "precursor_slot_preserved_without_forced_inference": True,
            "initiation_first_detectable_change_point_known_at_preserved": True,
            "confirmation_extreme_weakening_recovery_failure_preserved_when_source_proven": True,
            "rebase_transformation_invalidation_end_followthrough_slots_preserved": True,
            "formation_sequence_preserved_per_event": True,
            "source_gap_uncertainty_preserved": True,
            "connected_sequence_context_preserved_without_forced_merge": True,
            "observation_only_days_preserved": True,
            "all_v31_event_journeys_have_lifecycle_representation": True,
            "unnamed_state_transitions_preserved": True,
            "all_formation_runs_and_state_changes_materialized_in_behavior_path": True,
            "software_revision_pinned": True,
        },
        "reconciliation": {
            "pass": True,
            "source_count": len(sources),
            "ticker_days": int(totals["ticker_days"]),
            "source_rows": int(totals["source_rows"]),
            "regular_rows": int(totals["regular_rows"]),
            "nonregular_rows": int(totals["nonregular_rows"]),
            "full_observation_rows": int(totals["source_rows"]),
            "regular_behavior_rows": int(totals["regular_rows"]),
            "nonregular_observation_rows": int(totals["nonregular_rows"]),
            "excluded_rows": 0,
            "full_equals_regular_plus_nonregular": int(totals["source_rows"]) == int(totals["regular_rows"]) + int(totals["nonregular_rows"]),
            "zero_regular_ticker_days": int(totals["zero_regular_ticker_days"]),
            "zero_source_observation_ticker_days": int(totals["zero_source_observation_ticker_days"]),
            "formation_runs": int(totals["formation_runs"]),
            "semantic_markers": int(totals["semantic_markers"]),
            "event_journeys": int(totals["event_journeys"]),
            "right_censored_journeys": int(totals["right_censored_journeys"]),
            "no_forced_event_ticker_days": int(totals["no_forced_event_ticker_days"]),
            "phase_context_records": int(totals["phase_context_records"]),
            "behavior_day_profiles": int(totals["behavior_day_profiles"]),
            "behavior_lifecycle_journeys": int(totals["behavior_lifecycle_journeys"]),
            "behavior_lifecycle_open_journeys": int(totals["behavior_lifecycle_open_journeys"]),
            "behavior_lifecycle_contract_records": int(totals["behavior_lifecycle_contract_records"]),
            "behavior_paths": int(totals["behavior_paths"]),
            "behavior_state_transitions": int(totals["behavior_state_transitions"]),
            "behavior_day_profile_coverage_pass": int(totals["behavior_day_profiles"]) == int(totals["ticker_days"]),
            "behavior_lifecycle_journey_coverage_pass": int(totals["behavior_lifecycle_journeys"]) == int(totals["event_journeys"]),
            "behavior_lifecycle_contract_pass": int(totals["behavior_lifecycle_contract_records"]) == int(totals["behavior_lifecycle_journeys"]),
            "behavior_path_coverage_pass": int(totals["behavior_paths"]) == int(totals["ticker_days"]),
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
