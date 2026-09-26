from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from . import v32_full_observation_semantic_enrichment as legacy
from .v32_observation_envelope_dynamic import ensure_full_observation_caches_dynamic

SCHEMA = legacy.SCHEMA
STATUS = legacy.STATUS

_COUNT_KEYS = (
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
)

_REQUIRED_OUTPUTS = (
    "ticker_days",
    "formation_runs",
    "event_journeys",
    "phase_context",
    "full_observation_envelope",
    "regular_behavior_stream",
    "behavior_day_profiles",
    "behavior_lifecycle",
    "behavior_paths",
)


def _source_identity_digest(src: Mapping[str, Any], software_revision: str) -> str:
    payload = {
        "source_name": src.get("source_name"),
        "source_drive_id": src.get("source_drive_id"),
        "source_sha256": src.get("source_sha256"),
        "ticker_days": int(src.get("ticker_days", -1)),
        "source_rows": int(src.get("source_rows", -1)),
        "regular_rows": int(src.get("regular_rows", -1)),
        "nonregular_rows": int(src.get("nonregular_rows", -1)),
        "software_revision": software_revision,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def checkpoint_is_exact_source_compatible(
    path: Path,
    src: Mapping[str, Any],
    software_revision: str,
) -> bool:
    """Permit reuse when this source and semantic revision are exact.

    The old V3.2 checkpoint stored a global envelope digest. That digest changes
    when a future source is appended, even though earlier source bytes and
    semantics are unchanged. Dynamic reuse therefore binds to source ID/SHA,
    source counts, semantic revision and every output artifact hash instead of
    the historical universe cardinality/global digest.
    """
    if not path.is_file():
        return False
    try:
        cp = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if (
        cp.get("schema") != SCHEMA
        or cp.get("status") != "PASS"
        or cp.get("source") != src.get("source_name")
        or cp.get("software_revision") != software_revision
        or str(cp.get("source_drive_id") or "") != str(src.get("source_drive_id") or "")
        or str(cp.get("source_sha256") or "") != str(src.get("source_sha256") or "")
        or int(cp.get("ticker_days", -1)) != int(src.get("ticker_days", -2))
        or int(cp.get("source_rows", -1)) != int(src.get("source_rows", -2))
        or int(cp.get("regular_rows", -1)) != int(src.get("regular_rows", -2))
        or int(cp.get("nonregular_rows", -1)) != int(src.get("nonregular_rows", -2))
    ):
        return False
    outputs = cp.get("output_files")
    if not isinstance(outputs, dict):
        return False
    for role in _REQUIRED_OUTPUTS:
        meta = outputs.get(role)
        if not isinstance(meta, dict):
            return False
        name = str(meta.get("name") or "")
        expected_sha = str(meta.get("sha256") or "")
        expected_bytes = int(meta.get("bytes", -1))
        artifact = path.parent / name
        if not name or not expected_sha or expected_bytes < 0 or not artifact.is_file():
            return False
        if artifact.stat().st_size != expected_bytes:
            return False
        if legacy._sha256_file(artifact) != expected_sha:
            return False
    return True


def _output_meta(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "sha256": legacy._sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _process_source(
    *,
    db: sqlite3.Connection,
    src: Mapping[str, Any],
    output_root: Path,
    software_revision: str,
    envelope_digest: str,
    source_universe_digest: str,
    sample: list[dict[str, Any]],
) -> dict[str, Any]:
    source = str(src["source_name"])
    source_dir = output_root / legacy._slug(source)
    source_dir.mkdir(parents=True, exist_ok=True)

    td_path = source_dir / "ticker-days.jsonl.gz"
    runs_path = source_dir / "formation-runs.jsonl.gz"
    journeys_path = source_dir / "event-journeys.jsonl.gz"
    context_path = source_dir / "phase-context.jsonl.gz"
    full_layer_path = source_dir / "full-observation-envelope.jsonl.gz"
    regular_layer_path = source_dir / "regular-behavior-stream.jsonl.gz"
    behavior_day_path = source_dir / "behavior-day-profiles.jsonl.gz"
    behavior_lifecycle_path = source_dir / "behavior-lifecycle.jsonl.gz"
    behavior_path_path = source_dir / "behavior-paths.jsonl.gz"
    finals = (
        td_path,
        runs_path,
        journeys_path,
        context_path,
        full_layer_path,
        regular_layer_path,
        behavior_day_path,
        behavior_lifecycle_path,
        behavior_path_path,
    )
    tmps = tuple(path.with_suffix(path.suffix + ".tmp") for path in finals)
    for tmp in tmps:
        tmp.unlink(missing_ok=True)

    counts = Counter()
    allow_haka_haki = source == str(legacy.DEC_2024_CONTRACT["source_name"])

    with (
        gzip.open(tmps[0], "wt", encoding="utf-8", newline="\n") as td_fh,
        gzip.open(tmps[1], "wt", encoding="utf-8", newline="\n") as runs_fh,
        gzip.open(tmps[2], "wt", encoding="utf-8", newline="\n") as journeys_fh,
        gzip.open(tmps[3], "wt", encoding="utf-8", newline="\n") as context_fh,
        gzip.open(tmps[4], "wt", encoding="utf-8", newline="\n") as full_layer_fh,
        gzip.open(tmps[5], "wt", encoding="utf-8", newline="\n") as regular_layer_fh,
        gzip.open(tmps[6], "wt", encoding="utf-8", newline="\n") as behavior_day_fh,
        gzip.open(tmps[7], "wt", encoding="utf-8", newline="\n") as behavior_lifecycle_fh,
        gzip.open(tmps[8], "wt", encoding="utf-8", newline="\n") as behavior_path_fh,
    ):
        for packet in legacy.iter_envelope_cached(source):
            ticker = str(packet.get("ticker") or "")
            day = str(packet.get("date") or "")
            envelope = [dict(x) for x in packet.get("bars", [])]
            source_header = list(packet.get("source_header") or [])
            source_packet_fingerprint = packet.get("source_packet_fingerprint")
            if packet.get("all_source_columns_retained") is not True:
                raise RuntimeError(f"V32_DYNAMIC_SOURCE_COLUMNS_NOT_RETAINED:{source}:{ticker}:{day}")
            if not ticker or not day or not source_header:
                raise RuntimeError(f"V32_DYNAMIC_BAD_PACKET:{source}:{ticker}:{day}")
            for i, bar in enumerate(envelope):
                values = bar.get("source_field_values")
                if not isinstance(values, list) or len(values) != len(source_header):
                    raise RuntimeError(
                        f"V32_DYNAMIC_SOURCE_FIELD_RETRIEVAL_MISMATCH:{source}:{ticker}:{day}:{i}"
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

            carry, prev_day = legacy._carry_for_full_observation(db, ticker=ticker, day=day)
            td, runs, journeys = legacy.enrich_ticker_day(
                regular,
                source=source,
                source_identity=src,
                ticker=ticker,
                trading_date=day,
                carry_in=carry,
                previous_governed_date=prev_day,
                allow_haka_haki=allow_haka_haki,
            )
            td = legacy._rewrite_v32(td)
            runs = [legacy._rewrite_v32(dict(row)) for row in runs]
            journeys = [legacy._rewrite_v32(dict(row)) for row in journeys]
            behavior_day, lifecycle_records, behavior_path = legacy.enrich_behavior_lifecycle(
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
                raise RuntimeError(f"V32_DYNAMIC_LIFECYCLE_JOURNEY_COVERAGE_FAIL:{source}:{ticker}:{day}")

            behavior_day_fh.write(
                json.dumps(behavior_day, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
            for rec in lifecycle_records:
                behavior_lifecycle_fh.write(
                    json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                )
            behavior_path_fh.write(
                json.dumps(behavior_path, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
            legacy._store_journey_carry(db, ticker=ticker, day=day, journeys=journeys)

            phases = Counter(str(x.get("source_phase")) for x in envelope)
            first_source = legacy._terminal_summary(envelope[0] if envelope else None)
            last_regular = legacy._terminal_summary(regular[-1] if regular else None)
            last_source = legacy._terminal_summary(envelope[-1] if envelope else None)
            closing_match = legacy._closing_match_summary(envelope)
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
                    "behavior_lifecycle_schema": legacy.V32_LIFECYCLE_SCHEMA,
                    "behavior_lifecycle_journey_count": len(lifecycle_records),
                    "behavior_lifecycle_open_journey_count": int(
                        behavior_day["open_right_censored_journey_count"]
                    ),
                    "behavior_lifecycle_contract": behavior_day["lifecycle_contract"],
                }
            )
            td_fh.write(
                json.dumps(td, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
            for rec in runs:
                runs_fh.write(
                    json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                )
            for rec in journeys:
                journeys_fh.write(
                    json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
                )
            for bar in nonregular:
                context_fh.write(
                    json.dumps(
                        legacy._phase_context_record(source=source, ticker=ticker, day=day, bar=bar),
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
            counts["behavior_lifecycle_open_journeys"] += int(
                behavior_day["open_right_censored_journey_count"]
            )
            counts["behavior_lifecycle_contract_records"] += sum(
                int(bool(x.get("timing_contract_complete"))) for x in lifecycle_records
            )
            counts["behavior_paths"] += 1
            counts["behavior_state_transitions"] += int(behavior_path["state_transition_count"])
            if len(sample) < 150:
                sample.append(td)

    for tmp, final in zip(tmps, finals, strict=True):
        tmp.replace(final)
    db.commit()

    expected = {
        "ticker_days": int(src["ticker_days"]),
        "source_rows": int(src["source_rows"]),
        "regular_rows": int(src["regular_rows"]),
        "nonregular_rows": int(src["nonregular_rows"]),
    }
    for key, value in expected.items():
        if int(counts[key]) != value:
            raise RuntimeError(
                f"V32_DYNAMIC_SOURCE_RECONCILIATION_FAIL:{source}:{key}:{counts[key]}:{value}"
            )
    if counts["source_rows"] != counts["regular_rows"] + counts["nonregular_rows"]:
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_LAYER_ACCOUNTING_FAIL:{source}")
    if counts["behavior_day_profiles"] != counts["ticker_days"]:
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_BEHAVIOR_DAY_COVERAGE_FAIL:{source}")
    if counts["behavior_lifecycle_journeys"] != counts["event_journeys"]:
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_LIFECYCLE_JOURNEY_COVERAGE_FAIL:{source}")
    if counts["behavior_lifecycle_contract_records"] != counts["behavior_lifecycle_journeys"]:
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_LIFECYCLE_CONTRACT_FAIL:{source}")
    if counts["behavior_paths"] != counts["ticker_days"]:
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_BEHAVIOR_PATH_COVERAGE_FAIL:{source}")

    output_files = {
        role: _output_meta(path)
        for role, path in zip(_REQUIRED_OUTPUTS, finals, strict=True)
    }
    cp = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "envelope_digest_sha256": envelope_digest,
        "source_universe_manifest_digest_at_build": source_universe_digest,
        "source_identity_digest_sha256": _source_identity_digest(src, software_revision),
        "source": source,
        "software_revision": software_revision,
        "source_drive_id": src.get("source_drive_id"),
        "source_sha256": src.get("source_sha256"),
        **{key: int(counts[key]) for key in _COUNT_KEYS},
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
        "dynamic_source_universe": True,
    }
    (source_dir / "checkpoint.json").write_text(
        json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8"
    )
    return cp


def _baseline_aali_gate(db: sqlite3.Connection) -> dict[str, Any]:
    aali: dict[str, Any] = {}
    for day in ("2024-12-02", "2024-12-03"):
        row = db.execute(
            "SELECT source_observation_count,regular_count,last_regular_state_json,"
            "last_source_state_json,closing_match_state_json FROM days "
            "WHERE ticker='AALI' AND day=?",
            (day,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"V32_DYNAMIC_AALI_CONCORDANCE_DAY_MISSING:{day}")
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
    checks = (
        (aali["2024-12-02"]["source_observation_count"] == 104, "DEC2_SOURCE_COUNT"),
        (aali["2024-12-02"]["regular_count"] == 102, "DEC2_REGULAR_COUNT"),
        (str(dec2_regular.get("timestamp") or "").endswith("15:49:00"), "DEC2_LAST_REGULAR_TIME"),
        (float(dec2_regular.get("close") or 0) == 6175.0, "DEC2_LAST_REGULAR_CLOSE"),
        (str(dec2_source.get("timestamp") or "").endswith("16:01:00"), "DEC2_TERMINAL_TIME"),
        (float(dec2_source.get("close") or 0) == 6125.0, "DEC2_TERMINAL_CLOSE"),
        (dec2_source.get("source_phase") == "PRECLOSE_MATCH", "DEC2_TERMINAL_PHASE"),
        (aali["2024-12-03"]["source_observation_count"] == 150, "DEC3_SOURCE_COUNT"),
        (str(dec3_source.get("timestamp") or "").endswith("16:03:00"), "DEC3_TERMINAL_TIME"),
        (float(dec3_source.get("close") or 0) == 6125.0, "DEC3_TERMINAL_CLOSE"),
    )
    for passed, code in checks:
        if not passed:
            raise RuntimeError(f"V32_DYNAMIC_AALI_{code}_FAIL")
    carry_dec3, _ = legacy._carry_for_full_observation(db, ticker="AALI", day="2024-12-03")
    carry_source = dict((carry_dec3 or {}).get("last_source_supported_observation_state") or {})
    carry_regular = dict((carry_dec3 or {}).get("last_regular_session_state") or {})
    if float(carry_source.get("close") or 0) != 6125.0:
        raise RuntimeError("V32_DYNAMIC_AALI_DEC3_PRIOR_CARRY_FAIL")
    if float(carry_regular.get("close") or 0) != 6175.0:
        raise RuntimeError("V32_DYNAMIC_AALI_DEC3_PRIOR_REGULAR_CARRY_FAIL")
    return {"pass": True, "dec2": aali["2024-12-02"], "dec3": aali["2024-12-03"], "dec3_prior_carry": carry_dec3}


def run(*, output_root: Path, source_universe_manifest: Path) -> dict[str, Any]:
    software_revision = legacy._software_revision()
    catalog = ensure_full_observation_caches_dynamic(source_universe_manifest)
    if catalog.get("status") != "PASS" or catalog.get("dynamic_source_universe") is not True:
        raise RuntimeError("V32_DYNAMIC_ENVELOPE_CATALOG_NOT_PASS")
    sources = list(catalog["sources"])
    if not sources or len(sources) != int(catalog.get("source_count", -1)):
        raise RuntimeError("V32_DYNAMIC_SOURCE_CATALOG_CARDINALITY_FAIL")
    source_universe_digest = str(catalog.get("source_universe_manifest_digest") or "")
    envelope_digest = str(catalog["envelope_digest_sha256"])

    output_root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(output_root / "day-index.sqlite3")
    dates, indexed_days, indexed_source_rows, indexed_regular_rows = legacy._build_day_index(db, sources)
    if indexed_days != int(catalog["ticker_days"]):
        raise RuntimeError("V32_DYNAMIC_INDEX_TICKER_DAY_MISMATCH")
    if indexed_source_rows != int(catalog["source_rows"]):
        raise RuntimeError("V32_DYNAMIC_INDEX_SOURCE_ROW_MISMATCH")
    if indexed_regular_rows != int(catalog["regular_rows"]):
        raise RuntimeError("V32_DYNAMIC_INDEX_REGULAR_ROW_MISMATCH")
    legacy._init_journey_carry(db)

    totals = Counter()
    summaries: list[dict[str, Any]] = []
    sample: list[dict[str, Any]] = []
    reused_sources = 0
    built_sources = 0
    for src in sources:
        source = str(src["source_name"])
        source_dir = output_root / legacy._slug(source)
        checkpoint = source_dir / "checkpoint.json"
        if checkpoint_is_exact_source_compatible(checkpoint, src, software_revision):
            cp = json.loads(checkpoint.read_text(encoding="utf-8"))
            summaries.append(cp)
            for key in _COUNT_KEYS:
                totals[key] += int(cp.get(key, 0))
            legacy._restore_journey_carry(db, source_dir)
            reused_sources += 1
            continue
        cp = _process_source(
            db=db,
            src=src,
            output_root=output_root,
            software_revision=software_revision,
            envelope_digest=envelope_digest,
            source_universe_digest=source_universe_digest,
            sample=sample,
        )
        summaries.append(cp)
        for key in _COUNT_KEYS:
            totals[key] += int(cp.get(key, 0))
        built_sources += 1

    expected_totals = {
        "ticker_days": int(catalog["ticker_days"]),
        "source_rows": int(catalog["source_rows"]),
        "regular_rows": int(catalog["regular_rows"]),
        "nonregular_rows": int(catalog["nonregular_rows"]),
    }
    for key, value in expected_totals.items():
        if int(totals[key]) != value:
            raise RuntimeError(f"V32_DYNAMIC_GLOBAL_RECONCILIATION_FAIL:{key}:{totals[key]}:{value}")
    if totals["source_rows"] != totals["regular_rows"] + totals["nonregular_rows"]:
        raise RuntimeError("V32_DYNAMIC_GLOBAL_LAYER_ACCOUNTING_FAIL")
    if totals["behavior_day_profiles"] != totals["ticker_days"]:
        raise RuntimeError("V32_DYNAMIC_GLOBAL_BEHAVIOR_DAY_COVERAGE_FAIL")
    if totals["behavior_paths"] != totals["ticker_days"]:
        raise RuntimeError("V32_DYNAMIC_GLOBAL_BEHAVIOR_PATH_COVERAGE_FAIL")
    if totals["behavior_lifecycle_journeys"] != totals["event_journeys"]:
        raise RuntimeError("V32_DYNAMIC_GLOBAL_LIFECYCLE_JOURNEY_COVERAGE_FAIL")
    if totals["behavior_lifecycle_contract_records"] != totals["behavior_lifecycle_journeys"]:
        raise RuntimeError("V32_DYNAMIC_GLOBAL_LIFECYCLE_CONTRACT_FAIL")

    aali_gate = _baseline_aali_gate(db)
    sample_path = output_root / "compact-sample.jsonl.gz"
    legacy._write_gz_jsonl(sample_path, sample)

    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "software_revision": software_revision,
        "dynamic_source_universe": True,
        "source_universe_manifest_digest": source_universe_digest,
        "source_count_is_dynamic": True,
        "fixed_source_count_invariant_used": False,
        "behavior_lifecycle_schema": legacy.V32_LIFECYCLE_SCHEMA,
        "behavior_lifecycle_timing_fields": list(legacy.LIFECYCLE_TIMING_FIELDS),
        "v31_baseline": {
            "run_id": legacy.V31_RUN_ID,
            "artifact_id": legacy.V31_ARTIFACT_ID,
            "artifact_digest": legacy.V31_ARTIFACT_DIGEST,
            "corpus_digest_sha256": legacy.V31_CORPUS_DIGEST,
            "preserved_immutable": True,
            "role": "HISTORICAL_BASELINE_NOT_DYNAMIC_UNIVERSE_INVARIANT",
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
            "formation_sequence_preserved_per_event": True,
            "source_gap_uncertainty_preserved": True,
            "connected_sequence_context_preserved_without_forced_merge": True,
            "observation_only_days_preserved": True,
            "all_v31_event_journeys_have_lifecycle_representation": True,
            "unnamed_state_transitions_preserved": True,
            "all_formation_runs_and_state_changes_materialized_in_behavior_path": True,
            "software_revision_pinned": True,
            "dynamic_source_universe_bound": True,
            "exact_source_compatible_checkpoint_reuse": True,
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
            "full_equals_regular_plus_nonregular": True,
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
            "behavior_day_profile_coverage_pass": totals["behavior_day_profiles"] == totals["ticker_days"],
            "behavior_lifecycle_journey_coverage_pass": totals["behavior_lifecycle_journeys"] == totals["event_journeys"],
            "behavior_lifecycle_contract_pass": totals["behavior_lifecycle_contract_records"] == totals["behavior_lifecycle_journeys"],
            "behavior_path_coverage_pass": totals["behavior_paths"] == totals["ticker_days"],
            "governed_dates": len(dates),
            "reused_pass_sources": reused_sources,
            "built_sources": built_sources,
        },
        "aali_concordance_gate": aali_gate,
        "source_summaries": summaries,
        "manifest_sha256": None,
    }
    manifest["manifest_sha256"] = legacy._digest_obj(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    db.close()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-universe-manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = run(
        output_root=args.output_root,
        source_universe_manifest=args.source_universe_manifest,
    )
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "status": manifest["status"],
                "source_count": manifest["reconciliation"]["source_count"],
                "reused_pass_sources": manifest["reconciliation"]["reused_pass_sources"],
                "built_sources": manifest["reconciliation"]["built_sources"],
                "source_universe_manifest_digest": manifest["source_universe_manifest_digest"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
