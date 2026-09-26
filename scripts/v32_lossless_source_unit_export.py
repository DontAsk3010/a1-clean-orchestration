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


PROOF_SCHEMA = "A1_V32_LOSSLESS_SOURCE_UNIT_TRANSPORT_PROOF_V1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_obj(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    if not rows:
        raise RuntimeError("V32_SOURCE_UNIT_EMPTY")
    return rows


def find_source_dir(output_root: Path, source_name: str) -> tuple[Path, dict[str, Any]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for checkpoint in output_root.glob("*/checkpoint.json"):
        try:
            cp = load_json(checkpoint)
        except Exception:
            continue
        if str(cp.get("source") or "") == source_name:
            matches.append((checkpoint.parent, cp))
    if len(matches) != 1:
        raise RuntimeError(f"V32_SOURCE_UNIT_CARDINALITY:{source_name}:{len(matches)}")
    return matches[0]


def assert_authority(authority: dict[str, Any], request: dict[str, Any]) -> None:
    if authority.get("schema") != "A1_CLEAN_ACTIVE_AUTHORITY_LOCK_V1" or authority.get("status") != "ACTIVE":
        raise RuntimeError("V32_SOURCE_UNIT_AUTHORITY_NOT_ACTIVE")
    for key in (
        "lossless_artifact_transport_preferred_for_large_payloads",
        "transport_optimization_may_not_reduce_evidence",
        "artifact_integrity_manifest_required",
        "artifact_transport_integrity_readback_required",
        "full_verified_payload_read_required_before_semantic_pass",
        "connector_control_plane_thin_after_file_intake",
    ):
        if authority.get(key) is not True:
            raise RuntimeError(f"V32_SOURCE_UNIT_AUTHORITY_FLAG_FAIL:{key}")
    if request.get("schema") != "A1_V32_FULL_OBSERVATION_BEHAVIOR_REQUEST_V2":
        raise RuntimeError("V32_SOURCE_UNIT_REQUEST_SCHEMA_FAIL")
    if request.get("enabled") is not True:
        raise RuntimeError("V32_SOURCE_UNIT_HOLD_REQUEST_DISABLED")
    if request.get("formula_stage") != "CLOSED":
        raise RuntimeError("V32_SOURCE_UNIT_FORMULA_STAGE_FAIL")
    for key in (
        "dynamic_source_universe_required",
        "lossless_artifact_transport_preferred_for_large_payloads",
        "transport_optimization_may_not_reduce_evidence",
        "artifact_integrity_manifest_required",
        "full_verified_payload_read_required_before_semantic_pass",
        "connector_control_plane_thin_after_file_intake",
        "transport_integrity_proof_required",
    ):
        if request.get(key) is not True:
            raise RuntimeError(f"V32_SOURCE_UNIT_REQUEST_FLAG_FAIL:{key}")


def assert_global_manifest(manifest: dict[str, Any], request: dict[str, Any]) -> None:
    if manifest.get("schema") != "A1_V32_FULL_OBSERVATION_SEMANTIC_ENRICHMENT_V3" or manifest.get("status") != "PASS":
        raise RuntimeError("V32_SOURCE_UNIT_GLOBAL_MANIFEST_FAIL")
    if manifest.get("dynamic_source_universe") is not True or manifest.get("source_count_is_dynamic") is not True:
        raise RuntimeError("V32_SOURCE_UNIT_DYNAMIC_UNIVERSE_FAIL")
    if manifest.get("fixed_source_count_invariant_used") is not False:
        raise RuntimeError("V32_SOURCE_UNIT_FIXED_SOURCE_COUNT_USED")
    if str(manifest.get("software_revision") or "") != str(request.get("required_parent_revision") or ""):
        raise RuntimeError("V32_SOURCE_UNIT_SOFTWARE_REVISION_MISMATCH")
    rec = manifest.get("reconciliation") or {}
    if rec.get("pass") is not True or int(rec.get("excluded_rows", -1)) != 0:
        raise RuntimeError("V32_SOURCE_UNIT_GLOBAL_RECONCILIATION_FAIL")
    if rec.get("full_equals_regular_plus_nonregular") is not True:
        raise RuntimeError("V32_SOURCE_UNIT_GLOBAL_LAYER_ACCOUNTING_FAIL")


def verify_checkpoint_files(source_dir: Path, cp: dict[str, Any]) -> dict[str, Any]:
    if cp.get("status") != "PASS":
        raise RuntimeError("V32_SOURCE_UNIT_CHECKPOINT_NOT_PASS")
    outputs = cp.get("output_files")
    if not isinstance(outputs, dict) or not outputs:
        raise RuntimeError("V32_SOURCE_UNIT_OUTPUT_METADATA_MISSING")
    checked = 0
    for role, meta in outputs.items():
        if not isinstance(meta, dict):
            raise RuntimeError(f"V32_SOURCE_UNIT_BAD_OUTPUT_META:{role}")
        name = str(meta.get("name") or "")
        expected_sha = str(meta.get("sha256") or "")
        expected_bytes = int(meta.get("bytes", -1))
        path = source_dir / name
        if not name or not expected_sha or expected_bytes < 0 or not path.is_file():
            raise RuntimeError(f"V32_SOURCE_UNIT_OUTPUT_MISSING:{role}")
        if path.stat().st_size != expected_bytes:
            raise RuntimeError(f"V32_SOURCE_UNIT_OUTPUT_SIZE_FAIL:{role}")
        if sha256_file(path) != expected_sha:
            raise RuntimeError(f"V32_SOURCE_UNIT_OUTPUT_SHA_FAIL:{role}")
        checked += 1
    return {"checkpoint_output_files_verified": checked}


def scan_full_observation(source_dir: Path) -> dict[str, Any]:
    path = source_dir / "full-observation-envelope.jsonl.gz"
    if not path.is_file():
        raise RuntimeError("V32_SOURCE_UNIT_FULL_OBSERVATION_MISSING")
    packets = 0
    source_rows = 0
    regular_rows = 0
    nonregular_rows = 0
    duplicate_packets = 0
    duplicate_source_rows = 0
    timestamp_missing = 0
    timestamp_order_violations = 0
    first_date = None
    last_date = None
    first_ts = None
    last_ts = None
    seen_packets: set[tuple[str, str]] = set()

    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            ticker = str(row.get("ticker") or "")
            day = str(row.get("date") or "")
            if not ticker or not day:
                raise RuntimeError(f"V32_SOURCE_UNIT_PACKET_IDENTITY_MISSING:{line_no}")
            key = (ticker, day)
            if key in seen_packets:
                duplicate_packets += 1
            seen_packets.add(key)
            packets += 1
            first_date = day if first_date is None or day < first_date else first_date
            last_date = day if last_date is None or day > last_date else last_date
            bars = row.get("bars")
            if not isinstance(bars, list):
                raise RuntimeError(f"V32_SOURCE_UNIT_BARS_NOT_LIST:{line_no}")
            prev_ts = None
            seen_rows: set[int] = set()
            for bar in bars:
                if not isinstance(bar, dict):
                    raise RuntimeError(f"V32_SOURCE_UNIT_BAR_NOT_OBJECT:{line_no}")
                source_rows += 1
                if bool(bar.get("regular_behavior_eligible")):
                    regular_rows += 1
                else:
                    nonregular_rows += 1
                if bar.get("source_row") is not None:
                    src_row = int(bar["source_row"])
                    if src_row in seen_rows:
                        duplicate_source_rows += 1
                    seen_rows.add(src_row)
                ts = str(bar.get("timestamp") or "")
                if not ts:
                    timestamp_missing += 1
                    continue
                if prev_ts is not None and ts < prev_ts:
                    timestamp_order_violations += 1
                prev_ts = ts
                first_ts = ts if first_ts is None or ts < first_ts else first_ts
                last_ts = ts if last_ts is None or ts > last_ts else last_ts

    return {
        "ticker_days": packets,
        "source_rows": source_rows,
        "regular_rows": regular_rows,
        "nonregular_rows": nonregular_rows,
        "first_governed_date": first_date,
        "last_governed_date": last_date,
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "packet_duplicate_count": duplicate_packets,
        "source_row_duplicate_count": duplicate_source_rows,
        "timestamp_missing_count": timestamp_missing,
        "timestamp_order_violation_count": timestamp_order_violations,
    }


def zip_tree(root: Path, out: Path) -> None:
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            zf.write(path, path.relative_to(root).as_posix())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authority", type=Path, required=True)
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--source-name", required=True)
    ap.add_argument("--stage", type=Path, required=True)
    args = ap.parse_args()

    authority = load_json(args.authority)
    request = load_json(args.request)
    assert_authority(authority, request)
    output_root = args.output_root.resolve()
    global_manifest_path = output_root / "manifest.json"
    if not global_manifest_path.is_file():
        raise RuntimeError("V32_SOURCE_UNIT_GLOBAL_MANIFEST_MISSING")
    global_manifest = load_json(global_manifest_path)
    assert_global_manifest(global_manifest, request)

    source_dir, cp = find_source_dir(output_root, args.source_name)
    file_check = verify_checkpoint_files(source_dir, cp)
    observed = scan_full_observation(source_dir)
    for key in ("ticker_days", "source_rows", "regular_rows", "nonregular_rows"):
        if int(cp.get(key, -1)) != int(observed[key]):
            raise RuntimeError(f"V32_SOURCE_UNIT_COUNT_MISMATCH:{key}:{cp.get(key)}:{observed[key]}")
    if observed["source_rows"] != observed["regular_rows"] + observed["nonregular_rows"]:
        raise RuntimeError("V32_SOURCE_UNIT_LAYER_ACCOUNTING_FAIL")
    for key in (
        "packet_duplicate_count",
        "source_row_duplicate_count",
        "timestamp_missing_count",
        "timestamp_order_violation_count",
    ):
        if int(observed[key]) != 0:
            raise RuntimeError(f"V32_SOURCE_UNIT_INTEGRITY_FAIL:{key}:{observed[key]}")

    stage = args.stage.resolve()
    if stage.exists():
        shutil.rmtree(stage)
    package_root = stage / "package"
    unit_target = package_root / "source-unit" / source_dir.name
    unit_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, unit_target)
    (package_root / "control").mkdir(parents=True, exist_ok=True)
    shutil.copy2(global_manifest_path, package_root / "control" / "global-manifest.json")
    shutil.copy2(args.request, package_root / "control" / "request.json")
    shutil.copy2(args.authority, package_root / "control" / "authority-lock.json")

    before = inventory(package_root)
    before_digest = digest_obj(before)
    payload = stage / "v32-source-unit-lossless.zip"
    zip_tree(package_root, payload)

    with tempfile.TemporaryDirectory(prefix="a1-v32-source-unit-readback-") as td:
        extracted = Path(td) / "payload"
        extracted.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(payload, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise RuntimeError(f"V32_SOURCE_UNIT_ZIP_CRC_FAIL:{bad}")
            zf.extractall(extracted)
        after = inventory(extracted)
        after_digest = digest_obj(after)
        if before != after or before_digest != after_digest:
            raise RuntimeError("V32_SOURCE_UNIT_ROUNDTRIP_FAIL")
        readback_cp = load_json(extracted / "source-unit" / source_dir.name / "checkpoint.json")
        if digest_obj(cp) != digest_obj(readback_cp):
            raise RuntimeError("V32_SOURCE_UNIT_CHECKPOINT_READBACK_FAIL")

    proof = {
        "schema": PROOF_SCHEMA,
        "status": "PASS",
        "transport_scope": "ONE_COMPLETE_GOVERNED_SOURCE_UNIT_NO_SAMPLING",
        "source_name": args.source_name,
        "source_directory": source_dir.name,
        "authority_effective_date": authority.get("effective_date"),
        "formula_stage": request.get("formula_stage"),
        "software_revision": global_manifest.get("software_revision"),
        "source_universe_manifest_digest": global_manifest.get("source_universe_manifest_digest"),
        "global_manifest_sha256": sha256_file(global_manifest_path),
        "source_checkpoint_sha256": sha256_file(source_dir / "checkpoint.json"),
        "package_file_count": len(before),
        "package_uncompressed_bytes": sum(int(row["bytes"]) for row in before),
        "package_inventory_digest": before_digest,
        "roundtrip_inventory_digest": before_digest,
        "payload_zip_sha256": sha256_file(payload),
        "payload_zip_bytes": payload.stat().st_size,
        "observed_counts_and_ranges": observed,
        **file_check,
        "missing_file_count_after_roundtrip": 0,
        "extra_file_count_after_roundtrip": 0,
        "file_digest_mismatch_count_after_roundtrip": 0,
        "sampling_used": False,
        "rows_omitted_for_transport": 0,
        "field_pruning_used": False,
        "summary_substitution_for_payload_used": False,
        "raw_rows_sent_to_connector_or_chat": False,
        "canonical_current_mutated": False,
        "raw_mutated": False,
    }
    proof["proof_digest_sha256"] = digest_obj(proof)
    proof_path = stage / "TRANSPORT_INTEGRITY_PROOF.json"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "source_name": args.source_name,
        "payload_zip_sha256": proof["payload_zip_sha256"],
        "source_rows": observed["source_rows"],
        "first_timestamp": observed["first_timestamp"],
        "last_timestamp": observed["last_timestamp"],
        "proof": str(proof_path),
        "payload": str(payload),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
