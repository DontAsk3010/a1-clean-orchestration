from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from .config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
)
from .delta_artifacts import process_source_to_local, upload_json_payload
from .google_drive import build_drive_api
from .source_parity import (
    FOLDER_MIME,
    _create_folder,
    _download_json,
    _list_children,
    _safe_slug,
    _stable_source,
    _upload_file,
)
from .source_preflight import run_source_preflight

RECOVERY_SCHEMA = "A1_CANONICAL_CURRENT_RECOVERY_REQUEST_V1"
CHECKPOINT_SCHEMA = "A1_CANONICAL_CURRENT_RECOVERY_CHECKPOINT_V1"
FINAL_SCHEMA = "A1_CANONICAL_CURRENT_RECOVERY_PREPARE_RESULT_V1"
REQUEST_PATH = Path("canonical-current-recovery-requests/current.json")
DATA_PLANE_CONTROL_FILES = (
    "GLOBAL_DATA_PLANE_MANIFEST.json",
    "GLOBAL_SOURCE_DISCOVERY.json",
    "GLOBAL_SOURCE_COVERAGE_INDEX.json",
    "PERSISTENT_SOURCE_STATE.json",
    "LATEST_DELTA_REFRESH.json",
    "AI_SEMANTIC_DELTA_QUEUE.json",
)
SOURCE_LOGICAL_FOLDERS = (
    "00_MANIFESTS",
    "01_ACCESS_SHARDS",
    "02_SEMANTIC_BUNDLES",
    "03_MARKET_DAY_INDEX",
    "04_SEMANTIC_EVENT_CONTRACT",
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _github_sha() -> str:
    value = (os.environ.get("GITHUB_SHA") or "LOCAL_NO_GITHUB_SHA").strip()
    return value or "LOCAL_NO_GITHUB_SHA"


def _json_fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_request(path: Path = REQUEST_PATH) -> dict:
    request = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema": RECOVERY_SCHEMA,
        "enabled": True,
        "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
        "expected_missing_current_folder_id": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "parity_staging_folder_id": FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        "canonical_promotion_allowed": False,
        "raw_write_allowed": False,
        "heavy_behavior_research_allowed": False,
    }
    for key, expected in required.items():
        if request.get(key) != expected:
            raise RuntimeError(f"RECOVERY_REQUEST_LOCK_MISMATCH: {key}")
    for key in ("full_shadow_evidence_folder_id", "committed_control_bundle_folder_id"):
        if not str(request.get(key) or "").strip():
            raise RuntimeError(f"RECOVERY_REQUEST_MISSING: {key}")
    return request


def _assert_expected_current_missing(api, folder_id: str) -> dict:
    try:
        meta = api.files().get(
            fileId=folder_id,
            fields="id,name,mimeType,trashed,parents",
            supportsAllDrives=True,
        ).execute()
    except HttpError as exc:
        if getattr(getattr(exc, "resp", None), "status", None) == 404:
            return {"pass": True, "state": "NOT_FOUND_404", "folder_id": folder_id}
        raise
    raise RuntimeError(
        "RECOVERY_EXPECTED_CURRENT_NOT_MISSING: "
        f"id={meta.get('id')} name={meta.get('name')} trashed={meta.get('trashed')}"
    )


def _unique(items: list[dict], name: str) -> dict:
    rows = [item for item in items if item.get("name") == name]
    if len(rows) != 1:
        raise RuntimeError(f"RECOVERY_UNIQUE_CHILD_HOLD: {name}: count={len(rows)}")
    return rows[0]


def _evidence_family(check: dict) -> dict[str, dict]:
    if check.get("pass") is not True:
        raise RuntimeError("RECOVERY_HISTORICAL_FAMILY_NOT_PASS")
    out: dict[str, dict] = {}
    for row in check.get("files", []):
        name = str(row.get("name") or "")
        if (
            not name
            or name in out
            or row.get("pass") is not True
            or row.get("candidate_md5") != row.get("baseline_md5")
            or int(row.get("candidate_size", -1)) != int(row.get("baseline_size", -2))
        ):
            raise RuntimeError(f"RECOVERY_INVALID_HISTORICAL_FILE_EVIDENCE: {name}")
        out[name] = {
            "size": int(row["baseline_size"]),
            "md5": str(row["baseline_md5"]).lower(),
        }
    return out


def _load_full_shadow_evidence(api, folder_id: str) -> dict:
    root = _list_children(api, folder_id)
    final = _download_json(api, _unique(root, "FULL_SHADOW_PARITY_FINAL.json")["id"])
    if final.get("pass") is not True:
        raise RuntimeError("RECOVERY_FULL_SHADOW_FINAL_NOT_PASS")
    folders = sorted(
        [x for x in root if x.get("mimeType") == FOLDER_MIME and str(x.get("name", "")).startswith("SRC_")],
        key=lambda x: str(x.get("name")),
    )
    sources: list[dict] = []
    seen: set[str] = set()
    for folder in folders:
        items = _list_children(api, folder["id"])
        report_item = _unique(items, "SOURCE_PARITY_REPORT.json")
        report = _download_json(api, report_item["id"])
        if report.get("pass") is not True:
            raise RuntimeError(f"RECOVERY_SOURCE_EVIDENCE_NOT_PASS: {folder.get('name')}")
        source = report.get("source") or {}
        checks = report.get("checks") or {}
        drive_id = str(source.get("drive_id") or "")
        name = str(source.get("name") or "")
        if not drive_id or drive_id in seen:
            raise RuntimeError(f"RECOVERY_DUPLICATE_EVIDENCE_SOURCE: {drive_id}")
        seen.add(drive_id)
        stem = Path(name).stem
        stable = (checks.get("source_manifest_stable_fields") or {}).get("candidate")
        if not isinstance(stable, dict):
            raise RuntimeError(f"RECOVERY_STABLE_SOURCE_EVIDENCE_MISSING: {name}")
        sources.append({
            "source_index": int(report.get("source_index") or 0),
            "name": name,
            "drive_id": drive_id,
            "size": int(source.get("size") or -1),
            "drive_md5": str(source.get("drive_md5") or "").lower(),
            "stable_source": stable,
            "physical": _evidence_family(checks.get("physical_shards_exact_md5") or {}),
            "semantic": _evidence_family(checks.get("semantic_bundles_exact_md5") or {}),
            "semantic_manifest_evidence_id": _unique(items, f"CANDIDATE__{stem}__SEMANTIC_BUNDLES_MANIFEST.json")["id"],
            "market_index_evidence_id": _unique(items, f"CANDIDATE__{stem}__MARKET_DAY_INDEX.json")["id"],
            "historical_source_report_id": report_item["id"],
        })
    sources.sort(key=lambda r: (r["source_index"], r["name"], r["drive_id"]))
    if len(sources) != int(final.get("completed_source_count") or -1):
        raise RuntimeError("RECOVERY_EVIDENCE_SOURCE_COUNT_MISMATCH")
    final_ids = {str(r.get("drive_id")) for r in final.get("source_summaries", [])}
    if final_ids != seen:
        raise RuntimeError("RECOVERY_EVIDENCE_SOURCE_MEMBERSHIP_MISMATCH")
    compact = [
        {
            "source_index": r["source_index"],
            "name": r["name"],
            "drive_id": r["drive_id"],
            "size": r["size"],
            "drive_md5": r["drive_md5"],
            "stable_source": r["stable_source"],
            "physical": r["physical"],
            "semantic": r["semantic"],
        }
        for r in sources
    ]
    return {"final": final, "sources": sources, "source_count": len(sources), "evidence_fingerprint": _json_fingerprint(compact)}


def _validate_raw_sources(preflight: dict, evidence: dict) -> tuple[list[dict], list[dict]]:
    current = {str(r.get("drive_id")): r for r in preflight.get("required_sources", [])}
    evidence_ids = {r["drive_id"] for r in evidence["sources"]}
    selected: list[dict] = []
    for expected in evidence["sources"]:
        row = current.get(expected["drive_id"])
        if row is None:
            raise RuntimeError(f"RECOVERY_RAW_SOURCE_MISSING: {expected['name']}")
        checks = {
            "status": row.get("status") == "PASS_EXACT_MD5",
            "name": row.get("name") == expected["name"],
            "size": int(row.get("drive_size") or -1) == expected["size"],
            "md5": str(row.get("drive_md5") or "").lower() == expected["drive_md5"],
        }
        if not all(checks.values()):
            raise RuntimeError(f"RECOVERY_RAW_SOURCE_DRIFT: {expected['name']}: {checks}")
        selected.append(row)
    extras = [r for sid, r in current.items() if sid not in evidence_ids]
    return selected, sorted(extras, key=lambda r: str(r.get("name")))


def _hash_file(path: Path) -> dict:
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(8 * 1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
    return {"size": path.stat().st_size, "md5": md5.hexdigest()}


def _actual_family(paths: list[Path]) -> dict[str, dict]:
    return {path.name: _hash_file(path) for path in paths}


def _compare_expected_file_maps(actual: dict[str, dict], expected: dict[str, dict], label: str) -> None:
    if set(actual) != set(expected):
        raise RuntimeError(
            f"RECOVERY_{label}_FILESET_MISMATCH: missing={sorted(set(expected)-set(actual))} extra={sorted(set(actual)-set(expected))}"
        )
    bad = [name for name in sorted(expected) if actual[name] != expected[name]]
    if bad:
        raise RuntimeError(f"RECOVERY_{label}_HASH_MISMATCH: {bad[:10]}")


def _tree_fingerprint(root: Path) -> tuple[str, list[dict]]:
    if not root.is_dir():
        raise RuntimeError("RECOVERY_EVENT_CONTRACT_FOLDER_MISSING")
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        sha = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(4 * 1024 * 1024)
                if not chunk:
                    break
                sha.update(chunk)
        rows.append({"relative_path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha.hexdigest()})
    if not rows:
        raise RuntimeError("RECOVERY_EVENT_CONTRACT_EMPTY")
    return _json_fingerprint(rows), rows


def _compare_regenerated_source(root: Path, manifest: dict, expected: dict, reader_api) -> dict:
    stem = Path(expected["name"]).stem
    physical = _actual_family(sorted((root / "01_ACCESS_SHARDS").glob(f"{stem}__PHYSICAL_*.bin")))
    semantic = _actual_family(sorted((root / "02_SEMANTIC_BUNDLES").glob(f"{stem}__SEMANTIC_*.jsonl")))
    _compare_expected_file_maps(physical, expected["physical"], "PHYSICAL")
    _compare_expected_file_maps(semantic, expected["semantic"], "SEMANTIC")
    stable = _stable_source(manifest)
    if stable != expected["stable_source"]:
        raise RuntimeError(f"RECOVERY_SOURCE_STABLE_MANIFEST_MISMATCH: {expected['name']}")
    semantic_path = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    market_path = root / "03_MARKET_DAY_INDEX" / f"{stem}__MARKET_DAY_INDEX.json"
    if json.loads(semantic_path.read_text(encoding="utf-8")) != _download_json(reader_api, expected["semantic_manifest_evidence_id"]):
        raise RuntimeError(f"RECOVERY_SEMANTIC_MANIFEST_MISMATCH: {expected['name']}")
    if json.loads(market_path.read_text(encoding="utf-8")) != _download_json(reader_api, expected["market_index_evidence_id"]):
        raise RuntimeError(f"RECOVERY_MARKET_INDEX_MISMATCH: {expected['name']}")
    event_fp, event_rows = _tree_fingerprint(root / "04_SEMANTIC_EVENT_CONTRACT")
    return {
        "pass": True,
        "source_sha256": stable.get("source_sha256"),
        "physical_file_count": len(physical),
        "semantic_file_count": len(semantic),
        "event_contract_tree_fingerprint": event_fp,
        "event_contract_files": event_rows,
    }


def _source_paths(root: Path, source_name: str) -> dict[str, list[Path]]:
    stem = Path(source_name).stem
    event_root = root / "04_SEMANTIC_EVENT_CONTRACT"
    nested = [p for p in event_root.rglob("*") if p.is_file() and p.parent != event_root]
    if nested:
        raise RuntimeError("RECOVERY_EVENT_CONTRACT_NESTED_LAYOUT_UNSUPPORTED_FAIL_CLOSED")
    return {
        "00_MANIFESTS": [
            root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json",
            root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json",
        ],
        "01_ACCESS_SHARDS": sorted((root / "01_ACCESS_SHARDS").glob(f"{stem}__PHYSICAL_*.bin")),
        "02_SEMANTIC_BUNDLES": sorted((root / "02_SEMANTIC_BUNDLES").glob(f"{stem}__SEMANTIC_*.jsonl")),
        "03_MARKET_DAY_INDEX": [root / "03_MARKET_DAY_INDEX" / f"{stem}__MARKET_DAY_INDEX.json"],
        "04_SEMANTIC_EVENT_CONTRACT": sorted(p for p in event_root.iterdir() if p.is_file()),
    }


def _persist_source(writer_api, *, parent_id: str, source_index: int, source_name: str, root: Path) -> dict:
    source_folder_id = _create_folder(
        writer_api,
        parent_id=parent_id,
        name=f"SRC_{source_index:04d}_{_safe_slug(Path(source_name).stem)}_{_utc_stamp()}",
    )
    logical_ids: dict[str, str] = {}
    uploads: list[dict] = []
    for logical, paths in _source_paths(root, source_name).items():
        child = _create_folder(writer_api, parent_id=source_folder_id, name=logical)
        logical_ids[logical] = child
        for path in paths:
            if not path.is_file():
                raise RuntimeError(f"RECOVERY_SOURCE_ARTIFACT_MISSING: {path}")
            uploads.append({"logical": logical, **_upload_file(writer_api, parent_id=child, source=path, target_name=path.name)})
    if not uploads or not all(r.get("pass") is True for r in uploads):
        raise RuntimeError(f"RECOVERY_SOURCE_STAGING_UPLOAD_FAILED: {source_name}")
    return {"pass": True, "folder_id": source_folder_id, "logical_folder_ids": logical_ids, "upload_count": len(uploads)}


def _copy_drive_file(api, *, file_id: str, parent_id: str, name: str) -> dict:
    result = api.files().copy(
        fileId=file_id,
        body={"name": name, "parents": [parent_id]},
        fields="id,name,size,md5Checksum,parents",
        supportsAllDrives=True,
    ).execute()
    if result.get("name") != name:
        raise RuntimeError(f"RECOVERY_DRIVE_COPY_NAME_MISMATCH: {name}")
    return result


def _copy_folder_files(api, *, source_folder_id: str, target_folder_id: str) -> list[dict]:
    items = [x for x in _list_children(api, source_folder_id) if x.get("mimeType") != FOLDER_MIME]
    names = [str(x.get("name")) for x in items]
    if len(names) != len(set(names)):
        raise RuntimeError(f"RECOVERY_STAGED_SOURCE_DUPLICATE_NAMES: {source_folder_id}")
    return [
        _copy_drive_file(api, file_id=x["id"], parent_id=target_folder_id, name=str(x["name"]))
        for x in sorted(items, key=lambda r: str(r.get("name")))
    ]


def _find_run(api, suffix: str) -> tuple[dict | None, dict | None]:
    rows = sorted(
        [
            x for x in _list_children(api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID)
            if x.get("mimeType") == FOLDER_MIME
            and str(x.get("name", "")).startswith("CANONICAL_CURRENT_RECOVERY_PREPARE_")
            and str(x.get("name", "")).endswith(suffix)
        ],
        key=lambda x: str(x.get("name")), reverse=True,
    )
    for folder in rows:
        cps = sorted(
            [x for x in _list_children(api, folder["id"]) if x.get("mimeType") != FOLDER_MIME and str(x.get("name", "")).startswith("CHECKPOINT_")],
            key=lambda x: str(x.get("name")),
        )
        if cps:
            return folder, _download_json(api, cps[-1]["id"])
    return None, None


def _checkpoint_upload(api, run_folder_id: str, checkpoint: dict) -> None:
    name = f"CHECKPOINT_{int(checkpoint['sequence']):04d}_{_utc_stamp()}_{checkpoint['status']}.json"
    result = upload_json_payload(api, parent_id=run_folder_id, name=name, payload=checkpoint)
    if result.get("pass") is not True:
        raise RuntimeError("RECOVERY_CHECKPOINT_UPLOAD_FAILED")


def _validate_checkpoint(checkpoint: dict, *, request_fp: str, evidence_fp: str) -> None:
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "github_sha": _github_sha(),
        "request_fingerprint": request_fp,
        "evidence_fingerprint": evidence_fp,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
    }
    for key, value in expected.items():
        if checkpoint.get(key) != value:
            raise RuntimeError(f"RECOVERY_CHECKPOINT_IDENTITY_DRIFT: {key}")


def _assemble_candidate(writer_api, *, run_folder_id: str, completed: dict[str, dict], evidence: list[dict], controls_id: str) -> dict:
    candidate_id = _create_folder(writer_api, parent_id=run_folder_id, name=f"CANDIDATE_CURRENT_{_utc_stamp()}")
    targets = {logical: _create_folder(writer_api, parent_id=candidate_id, name=logical) for logical in SOURCE_LOGICAL_FOLDERS}
    copies: list[dict] = []
    for expected in evidence:
        staged = completed[expected["drive_id"]]["staging"]["logical_folder_ids"]
        for logical in SOURCE_LOGICAL_FOLDERS[:4]:
            copies.extend(_copy_folder_files(writer_api, source_folder_id=staged[logical], target_folder_id=targets[logical]))
    first_staged = completed[evidence[0]["drive_id"]]["staging"]["logical_folder_ids"]
    copies.extend(_copy_folder_files(writer_api, source_folder_id=first_staged["04_SEMANTIC_EVENT_CONTRACT"], target_folder_id=targets["04_SEMANTIC_EVENT_CONTRACT"]))
    control_items = [x for x in _list_children(writer_api, controls_id) if x.get("mimeType") != FOLDER_MIME]
    control_map = {str(x.get("name")): x for x in control_items}
    missing = sorted(set(DATA_PLANE_CONTROL_FILES) - set(control_map))
    if missing:
        raise RuntimeError(f"RECOVERY_COMMITTED_CONTROL_BUNDLE_INCOMPLETE: {missing}")
    for name in DATA_PLANE_CONTROL_FILES:
        copies.append(_copy_drive_file(writer_api, file_id=control_map[name]["id"], parent_id=targets["00_MANIFESTS"], name=name))
    readback = {}
    for logical, folder_id in targets.items():
        items = [x for x in _list_children(writer_api, folder_id) if x.get("mimeType") != FOLDER_MIME]
        names = [str(x.get("name")) for x in items]
        if len(names) != len(set(names)):
            raise RuntimeError(f"RECOVERY_CANDIDATE_DUPLICATE_NAMES: {logical}")
        readback[logical] = {"file_count": len(items), "names_fingerprint": _json_fingerprint(sorted(names))}
    expected_physical = sum(len(r["physical"]) for r in evidence)
    expected_semantic = sum(len(r["semantic"]) for r in evidence)
    checks = {
        "manifest_count": readback["00_MANIFESTS"]["file_count"] == len(evidence) * 2 + len(DATA_PLANE_CONTROL_FILES),
        "physical_count": readback["01_ACCESS_SHARDS"]["file_count"] == expected_physical,
        "semantic_count": readback["02_SEMANTIC_BUNDLES"]["file_count"] == expected_semantic,
        "market_index_count": readback["03_MARKET_DAY_INDEX"]["file_count"] == len(evidence),
        "event_contract_nonempty": readback["04_SEMANTIC_EVENT_CONTRACT"]["file_count"] > 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"RECOVERY_CANDIDATE_READBACK_COUNT_HOLD: {checks}")
    return {
        "pass": True,
        "candidate_folder_id": candidate_id,
        "candidate_folder_role": "STAGING_ONLY_NOT_CANONICAL_CURRENT",
        "logical_folder_ids": targets,
        "copy_count": len(copies),
        "readback": readback,
        "checks": checks,
    }


def run_canonical_current_recovery_prepare(request_path: Path = REQUEST_PATH) -> dict:
    request = _load_request(request_path)
    request_fp = _json_fingerprint(request)
    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    missing_reader = _assert_expected_current_missing(reader_api, request["expected_missing_current_folder_id"])
    missing_writer = _assert_expected_current_missing(writer_api, request["expected_missing_current_folder_id"])
    evidence = _load_full_shadow_evidence(reader_api, request["full_shadow_evidence_folder_id"])
    if int(request.get("baseline_source_count_observed") or -1) != evidence["source_count"]:
        raise RuntimeError("RECOVERY_REQUEST_BASELINE_SOURCE_COUNT_EVIDENCE_MISMATCH")
    preflight = run_source_preflight()
    if preflight.get("pass") is not True:
        raise RuntimeError("RECOVERY_RAW_SOURCE_PREFLIGHT_HOLD")
    selected, extras = _validate_raw_sources(preflight, evidence)
    selected_by_id = {str(r["drive_id"]): r for r in selected}

    suffix = f"_{_github_sha()[:12]}_{request_fp[:12]}"
    run_folder, checkpoint = _find_run(writer_api, suffix)
    resumed = run_folder is not None
    if run_folder is None:
        run_folder_name = f"CANONICAL_CURRENT_RECOVERY_PREPARE_{_utc_stamp()}{suffix}"
        run_folder_id = _create_folder(writer_api, parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, name=run_folder_name)
        sources_folder_id = _create_folder(writer_api, parent_id=run_folder_id, name="RECOVERED_SOURCES")
        checkpoint = {
            "schema": CHECKPOINT_SCHEMA,
            "status": "IN_PROGRESS",
            "sequence": 0,
            "run_folder_id": run_folder_id,
            "run_folder_name": run_folder_name,
            "sources_folder_id": sources_folder_id,
            "github_sha": _github_sha(),
            "request_fingerprint": request_fp,
            "evidence_fingerprint": evidence["evidence_fingerprint"],
            "generation_id": FROZEN_GENERATION_ID,
            "data_plane_impl_version": FROZEN_IMPL_VERSION,
            "completed_sources": {},
            "event_contract_tree_fingerprint": None,
            "next_exact_resume_source": evidence["sources"][0]["name"],
            "canonical_write_performed": False,
            "raw_write_performed": False,
        }
        _checkpoint_upload(writer_api, run_folder_id, checkpoint)
    else:
        run_folder_id = run_folder["id"]
        _validate_checkpoint(checkpoint, request_fp=request_fp, evidence_fp=evidence["evidence_fingerprint"])
        if checkpoint.get("status") == "PASS_PREPARED":
            final_item = _unique(_list_children(writer_api, run_folder_id), "RECOVERY_PREPARE_FINAL.json")
            final = _download_json(writer_api, final_item["id"])
            final["already_complete"] = True
            return final

    completed = dict(checkpoint.get("completed_sources") or {})
    expected_event_fp = checkpoint.get("event_contract_tree_fingerprint")
    ordered = evidence["sources"]
    for pos, expected in enumerate(ordered, start=1):
        drive_id = expected["drive_id"]
        if completed.get(drive_id, {}).get("pass") is True:
            continue
        checkpoint["status"] = "IN_PROGRESS"
        checkpoint["next_exact_resume_source"] = expected["name"]
        checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
        _checkpoint_upload(writer_api, run_folder_id, checkpoint)
        root = None
        try:
            root, engine_result, manifest = process_source_to_local(selected=selected_by_id[drive_id], reader_api=reader_api)
            comparison = _compare_regenerated_source(root, manifest, expected, reader_api)
            event_fp = comparison["event_contract_tree_fingerprint"]
            if expected_event_fp is None:
                expected_event_fp = event_fp
            elif event_fp != expected_event_fp:
                raise RuntimeError(f"RECOVERY_EVENT_CONTRACT_CROSS_SOURCE_DRIFT: {expected['name']}")
            staging = _persist_source(writer_api, parent_id=checkpoint["sources_folder_id"], source_index=pos, source_name=expected["name"], root=root)
            completed[drive_id] = {
                "pass": True,
                "source_index": pos,
                "source_name": expected["name"],
                "source_drive_id": drive_id,
                "source_sha256": comparison["source_sha256"],
                "physical_file_count": comparison["physical_file_count"],
                "semantic_file_count": comparison["semantic_file_count"],
                "event_contract_tree_fingerprint": event_fp,
                "historical_source_report_id": expected["historical_source_report_id"],
                "staging": staging,
                "engine_semantic_gate": engine_result.get("semantic_gate"),
            }
            checkpoint["completed_sources"] = completed
            checkpoint["event_contract_tree_fingerprint"] = expected_event_fp
            checkpoint["next_exact_resume_source"] = ordered[pos]["name"] if pos < len(ordered) else None
            checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
            _checkpoint_upload(writer_api, run_folder_id, checkpoint)
        except Exception as exc:
            checkpoint["status"] = "HOLD"
            checkpoint["completed_sources"] = completed
            checkpoint["hold"] = {"source": expected["name"], "reason": f"{type(exc).__name__}: {exc}", "at_utc": datetime.now(timezone.utc).isoformat()}
            checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
            _checkpoint_upload(writer_api, run_folder_id, checkpoint)
            raise
        finally:
            if root is not None:
                shutil.rmtree(root, ignore_errors=True)

    passed_ids = {sid for sid, row in completed.items() if row.get("pass") is True}
    if passed_ids != {row["drive_id"] for row in ordered}:
        raise RuntimeError("RECOVERY_COMPLETED_SOURCE_MEMBERSHIP_HOLD")
    assembly = _assemble_candidate(
        writer_api,
        run_folder_id=run_folder_id,
        completed=completed,
        evidence=ordered,
        controls_id=request["committed_control_bundle_folder_id"],
    )
    final = {
        "schema": FINAL_SCHEMA,
        "pass": True,
        "status": "PASS_PREPARED_STAGING_ONLY",
        "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
        "run_folder_id": run_folder_id,
        "resumed_existing_run": resumed,
        "github_sha": _github_sha(),
        "request_fingerprint": request_fp,
        "evidence_fingerprint": evidence["evidence_fingerprint"],
        "missing_current_reader": missing_reader,
        "missing_current_writer": missing_writer,
        "recovered_source_count": len(completed),
        "baseline_source_count_is_snapshot_not_invariant": True,
        "current_raw_extra_sources_not_promoted_by_recovery": [r.get("name") for r in extras],
        "source_body_validation": "PHYSICAL_AND_SEMANTIC_EXACT_NAME_SIZE_MD5_AGAINST_PRIOR_PASS_EVIDENCE; SEMANTIC_MANIFEST_AND_MARKET_INDEX_EXACT_JSON; SOURCE_MANIFEST_STABLE_FIELDS_EXACT",
        "event_contract_validation": "REGENERATED_BY_FROZEN_ENGINE_AND_IDENTICAL_ACROSS_ALL_RECOVERED_SOURCES; HISTORICAL_CURRENT_BYTE_SNAPSHOT_NOT_AVAILABLE",
        "controls_validation": "SERVER_SIDE_COPY_OF_EXACT_COMMITTED_DATA_PLANE_CONTROL_BUNDLE_FROM_LAST_GOVERNED_PROMOTION_SHADOW",
        "event_contract_tree_fingerprint": expected_event_fp,
        "assembly": assembly,
        "canonical_current_expected_old_id": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "canonical_write_performed": False,
        "raw_write_performed": False,
        "promotion_authorized": False,
        "next_gate": "SEPARATE_GOVERNED_PROMOTION_AND_POST_PROMOTION_READBACK_REQUIRED",
    }
    uploaded = upload_json_payload(writer_api, parent_id=run_folder_id, name="RECOVERY_PREPARE_FINAL.json", payload=final)
    if uploaded.get("pass") is not True:
        raise RuntimeError("RECOVERY_FINAL_REPORT_UPLOAD_FAILED")
    checkpoint["status"] = "PASS_PREPARED"
    checkpoint["next_exact_resume_source"] = None
    checkpoint["completed_sources"] = completed
    checkpoint["candidate_current_folder_id"] = assembly["candidate_folder_id"]
    checkpoint["canonical_write_performed"] = False
    checkpoint["raw_write_performed"] = False
    checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
    _checkpoint_upload(writer_api, run_folder_id, checkpoint)
    return final


def main() -> int:
    report = run_canonical_current_recovery_prepare()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("pass") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
