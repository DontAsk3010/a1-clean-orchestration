from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any


AUTHORITY_SCHEMA = "A1_CLEAN_ACTIVE_AUTHORITY_LOCK_V1"
REQUEST_SCHEMA = "A1_V32_FULL_OBSERVATION_BEHAVIOR_REQUEST_V2"
CORPUS_SCHEMA = "A1_V32_FULL_OBSERVATION_SEMANTIC_ENRICHMENT_V3"
PROOF_SCHEMA = "A1_V32_LOSSLESS_ARTIFACT_TRANSPORT_PROOF_V1"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _digest_obj(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    if not rows:
        raise RuntimeError("V32_TRANSPORT_EMPTY_CORPUS")
    return rows


def _expected_counts(manifest: dict[str, Any]) -> dict[str, int]:
    summaries = manifest.get("source_summaries")
    if not isinstance(summaries, list) or not summaries:
        raise RuntimeError("V32_TRANSPORT_SOURCE_SUMMARIES_MISSING")
    keys = ("ticker_days", "source_rows", "regular_rows", "nonregular_rows")
    totals = {key: 0 for key in keys}
    for row in summaries:
        if not isinstance(row, dict) or row.get("status") != "PASS":
            raise RuntimeError("V32_TRANSPORT_SOURCE_SUMMARY_NOT_PASS")
        for key in keys:
            totals[key] += int(row.get(key, -1))
            if int(row.get(key, -1)) < 0:
                raise RuntimeError(f"V32_TRANSPORT_SOURCE_SUMMARY_COUNT_MISSING:{key}")
    return totals


def _scan_full_observation(root: Path) -> dict[str, Any]:
    packet_count = 0
    bar_count = 0
    regular_rows = 0
    nonregular_rows = 0
    min_date: str | None = None
    max_date: str | None = None
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    packet_duplicate_count = 0
    source_row_duplicate_count = 0
    timestamp_missing_count = 0
    timestamp_order_violation_count = 0
    files = sorted(root.rglob("full-observation-envelope.jsonl.gz"))
    if not files:
        raise RuntimeError("V32_TRANSPORT_FULL_OBSERVATION_LAYER_MISSING")

    for path in files:
        seen_packets: set[tuple[str, str]] = set()
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                ticker = str(row.get("ticker") or "")
                day = str(row.get("date") or "")
                if not ticker or not day:
                    raise RuntimeError(f"V32_TRANSPORT_PACKET_IDENTITY_MISSING:{path}:{line_number}")
                key = (ticker, day)
                if key in seen_packets:
                    packet_duplicate_count += 1
                seen_packets.add(key)
                packet_count += 1
                min_date = day if min_date is None or day < min_date else min_date
                max_date = day if max_date is None or day > max_date else max_date

                bars = row.get("bars")
                if not isinstance(bars, list):
                    raise RuntimeError(f"V32_TRANSPORT_BARS_NOT_LIST:{path}:{line_number}")
                prev_ts: str | None = None
                seen_source_rows: set[int] = set()
                for bar in bars:
                    if not isinstance(bar, dict):
                        raise RuntimeError(f"V32_TRANSPORT_BAR_NOT_OBJECT:{path}:{line_number}")
                    bar_count += 1
                    if bool(bar.get("regular_behavior_eligible")):
                        regular_rows += 1
                    else:
                        nonregular_rows += 1
                    src_row = bar.get("source_row")
                    if src_row is not None:
                        src_row_i = int(src_row)
                        if src_row_i in seen_source_rows:
                            source_row_duplicate_count += 1
                        seen_source_rows.add(src_row_i)
                    ts = str(bar.get("timestamp") or "")
                    if not ts:
                        timestamp_missing_count += 1
                        continue
                    if prev_ts is not None and ts < prev_ts:
                        timestamp_order_violation_count += 1
                    prev_ts = ts
                    min_timestamp = ts if min_timestamp is None or ts < min_timestamp else min_timestamp
                    max_timestamp = ts if max_timestamp is None or ts > max_timestamp else max_timestamp

    return {
        "full_observation_files": len(files),
        "ticker_days": packet_count,
        "source_rows": bar_count,
        "regular_rows": regular_rows,
        "nonregular_rows": nonregular_rows,
        "first_governed_date": min_date,
        "last_governed_date": max_date,
        "first_timestamp": min_timestamp,
        "last_timestamp": max_timestamp,
        "packet_duplicate_count": packet_duplicate_count,
        "source_row_duplicate_count": source_row_duplicate_count,
        "timestamp_missing_count": timestamp_missing_count,
        "timestamp_order_violation_count": timestamp_order_violation_count,
    }


def _assert_authority(authority: dict[str, Any], request: dict[str, Any]) -> None:
    if authority.get("schema") != AUTHORITY_SCHEMA or authority.get("status") != "ACTIVE":
        raise RuntimeError("V32_TRANSPORT_AUTHORITY_NOT_ACTIVE")
    required_authority = (
        "lossless_artifact_transport_preferred_for_large_payloads",
        "transport_optimization_may_not_reduce_evidence",
        "artifact_integrity_manifest_required",
        "artifact_transport_integrity_readback_required",
        "full_verified_payload_read_required_before_semantic_pass",
        "connector_control_plane_thin_after_file_intake",
    )
    for key in required_authority:
        if authority.get(key) is not True:
            raise RuntimeError(f"V32_TRANSPORT_AUTHORITY_FLAG_FAIL:{key}")
    if request.get("schema") != REQUEST_SCHEMA:
        raise RuntimeError("V32_TRANSPORT_REQUEST_SCHEMA_FAIL")
    if request.get("enabled") is not True:
        raise RuntimeError("V32_TRANSPORT_HOLD_REQUEST_DISABLED")
    if request.get("formula_stage") != "CLOSED":
        raise RuntimeError("V32_TRANSPORT_FORMULA_STAGE_MUST_BE_CLOSED")
    required_request = (
        "dynamic_source_universe_required",
        "lossless_artifact_transport_preferred_for_large_payloads",
        "transport_optimization_may_not_reduce_evidence",
        "artifact_integrity_manifest_required",
        "full_verified_payload_read_required_before_semantic_pass",
        "connector_control_plane_thin_after_file_intake",
        "transport_integrity_proof_required",
    )
    for key in required_request:
        if request.get(key) is not True:
            raise RuntimeError(f"V32_TRANSPORT_REQUEST_FLAG_FAIL:{key}")
    if request.get("fixed_source_count_as_universe_authority_forbidden") is not True:
        raise RuntimeError("V32_TRANSPORT_FIXED_SOURCE_COUNT_PROHIBITION_MISSING")


def _assert_corpus(manifest: dict[str, Any], request: dict[str, Any]) -> None:
    if manifest.get("schema") != CORPUS_SCHEMA or manifest.get("status") != "PASS":
        raise RuntimeError("V32_TRANSPORT_CORPUS_MANIFEST_NOT_PASS")
    if manifest.get("dynamic_source_universe") is not True:
        raise RuntimeError("V32_TRANSPORT_DYNAMIC_SOURCE_UNIVERSE_FALSE")
    if manifest.get("source_count_is_dynamic") is not True:
        raise RuntimeError("V32_TRANSPORT_SOURCE_COUNT_NOT_DYNAMIC")
    if manifest.get("fixed_source_count_invariant_used") is not False:
        raise RuntimeError("V32_TRANSPORT_FIXED_SOURCE_COUNT_USED")
    if str(manifest.get("software_revision") or "") != str(request.get("required_parent_revision") or ""):
        raise RuntimeError("V32_TRANSPORT_SOFTWARE_REVISION_MISMATCH")
    rec = manifest.get("reconciliation") or {}
    if rec.get("pass") is not True or int(rec.get("excluded_rows", -1)) != 0:
        raise RuntimeError("V32_TRANSPORT_CORPUS_RECONCILIATION_FAIL")
    if rec.get("full_equals_regular_plus_nonregular") is not True:
        raise RuntimeError("V32_TRANSPORT_CORPUS_LAYER_ACCOUNTING_FAIL")
    contract = manifest.get("contract") or {}
    if contract.get("full_source_supported_observation_envelope_preserved") is not True:
        raise RuntimeError("V32_TRANSPORT_FULL_ENVELOPE_NOT_PRESERVED")
    if contract.get("all_source_columns_retrievable_from_full_observation_layer") is not True:
        raise RuntimeError("V32_TRANSPORT_SOURCE_COLUMNS_NOT_RETRIEVABLE")
    if contract.get("source_values_retained_for_every_observation") is not True:
        raise RuntimeError("V32_TRANSPORT_SOURCE_VALUES_NOT_RETAINED")


def _zip_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(source).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()

    authority = _load_json(args.authority)
    request = _load_json(args.request)
    _assert_authority(authority, request)

    root = args.output_root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"V32_TRANSPORT_OUTPUT_ROOT_MISSING:{root}")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("V32_TRANSPORT_CORPUS_MANIFEST_MISSING")
    manifest = _load_json(manifest_path)
    _assert_corpus(manifest, request)

    expected = _expected_counts(manifest)
    observed = _scan_full_observation(root)
    for key in ("ticker_days", "source_rows", "regular_rows", "nonregular_rows"):
        if int(expected[key]) != int(observed[key]):
            raise RuntimeError(f"V32_TRANSPORT_COUNT_MISMATCH:{key}:{expected[key]}:{observed[key]}")
    if observed["source_rows"] != observed["regular_rows"] + observed["nonregular_rows"]:
        raise RuntimeError("V32_TRANSPORT_OBSERVED_LAYER_ACCOUNTING_FAIL")
    if observed["packet_duplicate_count"] != 0:
        raise RuntimeError("V32_TRANSPORT_DUPLICATE_TICKER_DAY_PACKET")
    if observed["source_row_duplicate_count"] != 0:
        raise RuntimeError("V32_TRANSPORT_DUPLICATE_SOURCE_ROW")
    if observed["timestamp_missing_count"] != 0:
        raise RuntimeError("V32_TRANSPORT_TIMESTAMP_MISSING")
    if observed["timestamp_order_violation_count"] != 0:
        raise RuntimeError("V32_TRANSPORT_TIMESTAMP_ORDER_FAIL")

    source_inventory = _inventory(root)
    source_inventory_digest = _digest_obj(source_inventory)
    stage = args.stage.resolve()
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    payload_zip = stage / "v32-full-corpus-lossless.zip"
    _zip_tree(root, payload_zip)

    with tempfile.TemporaryDirectory(prefix="a1-v32-transport-readback-") as td:
        extracted = Path(td) / "payload"
        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(payload_zip, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise RuntimeError(f"V32_TRANSPORT_ZIP_CRC_FAIL:{bad}")
            zf.extractall(extracted)
        roundtrip_inventory = _inventory(extracted)
        roundtrip_digest = _digest_obj(roundtrip_inventory)
        if source_inventory != roundtrip_inventory or source_inventory_digest != roundtrip_digest:
            raise RuntimeError("V32_TRANSPORT_ROUNDTRIP_INVENTORY_MISMATCH")
        readback_manifest = _load_json(extracted / "manifest.json")
        if _digest_obj(manifest) != _digest_obj(readback_manifest):
            raise RuntimeError("V32_TRANSPORT_MANIFEST_READBACK_MISMATCH")

    proof = {
        "schema": PROOF_SCHEMA,
        "status": "PASS",
        "transport_mode": "LOSSLESS_ACTIONS_ARTIFACT_ZIP_THIN_CONTROL_PLANE",
        "authority_effective_date": authority.get("effective_date"),
        "request_schema": request.get("schema"),
        "request_enabled": request.get("enabled"),
        "formula_stage": request.get("formula_stage"),
        "software_revision": manifest.get("software_revision"),
        "source_universe_manifest_digest": manifest.get("source_universe_manifest_digest"),
        "corpus_manifest_sha256": _sha256_file(manifest_path),
        "corpus_manifest_object_digest": _digest_obj(manifest),
        "file_count": len(source_inventory),
        "total_uncompressed_bytes": sum(int(row["bytes"]) for row in source_inventory),
        "source_inventory_digest": source_inventory_digest,
        "roundtrip_inventory_digest": source_inventory_digest,
        "payload_zip_sha256": _sha256_file(payload_zip),
        "payload_zip_bytes": payload_zip.stat().st_size,
        "expected_counts": expected,
        "observed_counts_and_ranges": observed,
        "missing_file_count_after_roundtrip": 0,
        "extra_file_count_after_roundtrip": 0,
        "file_digest_mismatch_count_after_roundtrip": 0,
        "order_preserved_by_exact_file_sha256_roundtrip": True,
        "zip_crc_readback_pass": True,
        "manifest_exact_readback_pass": True,
        "sampling_used": False,
        "field_pruning_used": False,
        "summary_substitution_for_full_payload_used": False,
        "raw_rows_sent_to_connector_or_chat": False,
        "connector_control_plane_thin": True,
        "semantic_authority_changed": False,
        "canonical_current_mutated": False,
        "raw_mutated": False,
    }
    proof["proof_digest_sha256"] = _digest_obj(proof)
    (stage / "TRANSPORT_INTEGRITY_PROOF.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({
        "status": "PASS",
        "proof": str(stage / "TRANSPORT_INTEGRITY_PROOF.json"),
        "payload": str(payload_zip),
        "payload_zip_sha256": proof["payload_zip_sha256"],
        "file_count": proof["file_count"],
        "source_rows": observed["source_rows"],
        "first_timestamp": observed["first_timestamp"],
        "last_timestamp": observed["last_timestamp"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
