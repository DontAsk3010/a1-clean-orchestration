from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    CANONICAL_CURRENT_FOLDER_NAME,
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    FROZEN_RAW_FOLDER_DRIVE_ID,
    PARITY_STAGING_FOLDER_NAME,
    DataPlaneConfig,
)
from .frozen_v2 import run_delta
from .google_drive import build_drive_api
from .parity import STABLE_SOURCE_KEYS
from .source_parity import (
    FOLDER_MIME,
    _SingleSourceDriveApi,
    _assert_folder,
    _baseline_runtime_children,
    _candidate_files,
    _compare_hashed_file_family,
    _create_folder,
    _download_json,
    _exact_named,
    _list_children,
    _safe_slug,
    _single_source_from_global,
    _stable_source,
    _upload_file,
)
from .source_preflight import run_source_preflight

FULL_SHADOW_GATE = "FULL_DYNAMIC_CORPUS_WINDOWS_FROZEN_V2_SHADOW_PARITY"
CHECKPOINT_SCHEMA = "A1_FULL_SHADOW_PARITY_CHECKPOINT_V1"
FINAL_REPORT_NAME = "FULL_SHADOW_PARITY_FINAL.json"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _source_universe_rows(preflight: dict) -> list[dict]:
    rows = []
    for row in preflight.get("required_sources", []):
        rows.append(
            {
                "name": row.get("name"),
                "drive_id": row.get("drive_id"),
                "size": row.get("drive_size"),
                "md5": row.get("drive_md5"),
                "status": row.get("status"),
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("name")), str(row.get("drive_id"))))


def _source_universe_fingerprint(preflight: dict) -> str:
    payload = json.dumps(
        _source_universe_rows(preflight),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _github_sha() -> str:
    value = (os.environ.get("GITHUB_SHA") or "LOCAL_NO_GITHUB_SHA").strip()
    return value or "LOCAL_NO_GITHUB_SHA"


def _run_key(preflight: dict) -> str:
    return f"{_github_sha()[:12]}_{_source_universe_fingerprint(preflight)[:12]}"


def _checkpoint_files(api, run_folder_id: str) -> list[dict]:
    return sorted(
        [
            item
            for item in _list_children(api, run_folder_id)
            if item.get("mimeType") != FOLDER_MIME
            and str(item.get("name", "")).startswith("CHECKPOINT_")
            and str(item.get("name", "")).endswith(".json")
        ],
        key=lambda item: str(item.get("name")),
    )


def _latest_checkpoint(api, run_folder_id: str) -> tuple[dict | None, dict | None]:
    files = _checkpoint_files(api, run_folder_id)
    if not files:
        return None, None
    item = files[-1]
    return item, _download_json(api, item["id"])


def _matching_run_folders(api, staging_id: str, run_key: str) -> list[dict]:
    suffix = "_" + run_key
    return sorted(
        [
            item
            for item in _list_children(api, staging_id)
            if item.get("mimeType") == FOLDER_MIME
            and str(item.get("name", "")).startswith("FULL_SHADOW_PARITY_")
            and str(item.get("name", "")).endswith(suffix)
        ],
        key=lambda item: str(item.get("name")),
        reverse=True,
    )


def _upload_json(api, *, parent_id: str, name: str, payload: dict) -> dict:
    fd, temp_name = tempfile.mkstemp(prefix="a1-full-shadow-json-", suffix=".json")
    os.close(fd)
    path = Path(temp_name)
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return _upload_file(api, parent_id=parent_id, source=path, target_name=name)
    finally:
        path.unlink(missing_ok=True)


def _checkpoint_name(sequence: int, status: str) -> str:
    return f"CHECKPOINT_{sequence:04d}_{_utc_stamp()}_{status}.json"


def _persist_checkpoint(api, *, run_folder_id: str, checkpoint: dict) -> dict:
    sequence = int(checkpoint.get("checkpoint_sequence", 0))
    status = str(checkpoint.get("status", "UNKNOWN"))
    result = _upload_json(
        api,
        parent_id=run_folder_id,
        name=_checkpoint_name(sequence, status),
        payload=checkpoint,
    )
    if not result.get("pass"):
        raise RuntimeError("FULL_SHADOW_CHECKPOINT_UPLOAD_RECONCILIATION_FAILED")
    return result


def _new_checkpoint(*, preflight: dict, run_folder_id: str, run_folder_name: str) -> dict:
    sources = _source_universe_rows(preflight)
    return {
        "schema": CHECKPOINT_SCHEMA,
        "gate": FULL_SHADOW_GATE,
        "status": "IN_PROGRESS",
        "checkpoint_sequence": 0,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_folder_id": run_folder_id,
        "run_folder_name": run_folder_name,
        "github_sha": _github_sha(),
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": _source_universe_fingerprint(preflight),
        "canonical_source_count_observed": len(sources),
        "source_count_is_not_an_invariant": True,
        "required_sources": sources,
        "completed_sources": {},
        "current_source": None,
        "holds": [],
        "next_exact_resume_source": sources[0]["name"] if sources else None,
    }


def _validate_resume_checkpoint(checkpoint: dict, preflight: dict) -> None:
    expected = {
        "schema": CHECKPOINT_SCHEMA,
        "gate": FULL_SHADOW_GATE,
        "github_sha": _github_sha(),
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": _source_universe_fingerprint(preflight),
    }
    for key, value in expected.items():
        if checkpoint.get(key) != value:
            raise RuntimeError(
                f"FULL_SHADOW_RESUME_IDENTITY_MISMATCH: key={key} expected={value!r} actual={checkpoint.get(key)!r}"
            )
    if checkpoint.get("required_sources") != _source_universe_rows(preflight):
        raise RuntimeError("FULL_SHADOW_RESUME_SOURCE_UNIVERSE_DRIFT")


def _find_or_create_run(api, preflight: dict) -> tuple[str, str, dict, bool]:
    run_key = _run_key(preflight)
    for folder in _matching_run_folders(api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, run_key):
        _, checkpoint = _latest_checkpoint(api, folder["id"])
        if checkpoint is None:
            continue
        try:
            _validate_resume_checkpoint(checkpoint, preflight)
        except RuntimeError:
            continue
        status = checkpoint.get("status")
        if status in {"IN_PROGRESS", "HOLD"}:
            return folder["id"], folder["name"], checkpoint, True
        if status == "PASS":
            return folder["id"], folder["name"], checkpoint, True

    folder_name = f"FULL_SHADOW_PARITY_{_utc_stamp()}_{run_key}"
    folder_id = _create_folder(
        api,
        parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        name=folder_name,
    )
    checkpoint = _new_checkpoint(
        preflight=preflight,
        run_folder_id=folder_id,
        run_folder_name=folder_name,
    )
    _persist_checkpoint(api, run_folder_id=folder_id, checkpoint=checkpoint)
    return folder_id, folder_name, checkpoint, False


def _source_evidence_paths(candidate_root: Path, source_name: str) -> list[Path]:
    stem = Path(source_name).stem
    manifest_dir = candidate_root / "00_MANIFESTS"
    paths: list[Path] = []
    if manifest_dir.exists():
        for path in sorted(manifest_dir.iterdir()):
            if path.is_file() and (
                path.name.startswith(stem)
                or path.name
                in {
                    "GLOBAL_DATA_PLANE_MANIFEST.json",
                    "GLOBAL_SOURCE_DISCOVERY.json",
                    "LATEST_DELTA_REFRESH.json",
                }
            ):
                paths.append(path)
    market = candidate_root / "03_MARKET_DAY_INDEX" / f"{stem}__MARKET_DAY_INDEX.json"
    if market.is_file():
        paths.append(market)
    return paths


def _persist_source_evidence(
    writer_api,
    *,
    run_folder_id: str,
    source_index: int,
    source_name: str,
    candidate_root: Path,
    report: dict,
) -> dict:
    source_folder_name = f"SRC_{source_index:04d}_{_safe_slug(Path(source_name).stem)}"
    source_folder_id = _create_folder(
        writer_api,
        parent_id=run_folder_id,
        name=source_folder_name,
    )
    uploads: list[dict] = []
    for path in _source_evidence_paths(candidate_root, source_name):
        uploads.append(
            _upload_file(
                writer_api,
                parent_id=source_folder_id,
                source=path,
                target_name="CANDIDATE__" + path.name,
            )
        )
    evidence_pass = bool(uploads) and all(row.get("pass") is True for row in uploads)
    report = dict(report)
    report["staging_evidence"] = {
        "pass": evidence_pass,
        "folder_id": source_folder_id,
        "folder_name": source_folder_name,
        "uploads": uploads,
        "persistence_mode": "SOURCE_SCOPED_HASH_AND_CONTROL_EVIDENCE_WITHIN_FULL_SHADOW_RUN",
    }
    report["pass"] = bool(report.get("pass")) and evidence_pass
    report_upload = _upload_json(
        writer_api,
        parent_id=source_folder_id,
        name="SOURCE_PARITY_REPORT.json",
        payload=report,
    )
    report["source_report_upload"] = report_upload
    report["pass"] = report["pass"] and report_upload.get("pass") is True
    return report


def _run_verified_source(
    *,
    selected: dict,
    source_index: int,
    preflight: dict,
    reader_api,
    writer_api,
    run_folder_id: str,
    manifest_items: list[dict],
    access_items: list[dict],
    semantic_items: list[dict],
    market_items: list[dict],
    baseline_global: dict,
) -> dict:
    source_name = str(selected["name"])
    if selected.get("status") != "PASS_EXACT_MD5":
        raise RuntimeError(f"SOURCE_IDENTITY_NOT_EXACT: {source_name}: {selected.get('status')}")

    source_meta = (
        reader_api.files()
        .get(
            fileId=selected["drive_id"],
            fields="id,name,mimeType,size,modifiedTime,parents,md5Checksum",
            supportsAllDrives=True,
        )
        .execute()
    )
    if source_meta.get("name") != source_name:
        raise RuntimeError(f"SOURCE_METADATA_NAME_DRIFT: {source_name}")
    if int(source_meta.get("size", -1)) != int(selected.get("drive_size", -2)):
        raise RuntimeError(f"SOURCE_METADATA_SIZE_DRIFT: {source_name}")
    if source_meta.get("md5Checksum") != selected.get("drive_md5"):
        raise RuntimeError(f"SOURCE_METADATA_MD5_DRIFT: {source_name}")

    temp_parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()).resolve()
    run_root = Path(tempfile.mkdtemp(prefix="a1-full-shadow-source-", dir=str(temp_parent))).resolve()
    scratch = run_root / "_scratch"
    try:
        config = DataPlaneConfig(
            engine_root=run_root,
            raw_dir=Path(os.environ["A1_RAW_DIR"]).expanduser().resolve(),
            runtime_ingest_dir=run_root,
            raw_folder_drive_id=FROZEN_RAW_FOLDER_DRIVE_ID,
            current_folder_drive_id=FROZEN_CURRENT_FOLDER_DRIVE_ID,
            parity_staging_folder_drive_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
            run_root=run_root,
            scratch_dir=scratch,
            generation_id=FROZEN_GENERATION_ID,
            data_plane_impl_version=FROZEN_IMPL_VERSION,
        )
        scratch.mkdir(parents=True, exist_ok=True)
        delta_result = run_delta(config, _SingleSourceDriveApi(reader_api, source_meta))

        stem = Path(source_name).stem
        source_manifest_name = f"{stem}__DATA_PLANE_MANIFEST.json"
        semantic_manifest_name = f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
        market_index_name = f"{stem}__MARKET_DAY_INDEX.json"
        candidate_manifest_dir = run_root / "00_MANIFESTS"

        candidate_source_manifest = json.loads(
            (candidate_manifest_dir / source_manifest_name).read_text(encoding="utf-8")
        )
        baseline_source_manifest = _download_json(
            reader_api,
            _exact_named(manifest_items, source_manifest_name)["id"],
        )
        candidate_global = json.loads(
            (candidate_manifest_dir / "GLOBAL_DATA_PLANE_MANIFEST.json").read_text(encoding="utf-8")
        )
        candidate_global_source = _single_source_from_global(candidate_global, selected["drive_id"])
        baseline_global_source = _single_source_from_global(baseline_global, selected["drive_id"])
        candidate_semantic_manifest = json.loads(
            (candidate_manifest_dir / semantic_manifest_name).read_text(encoding="utf-8")
        )
        baseline_semantic_manifest = _download_json(
            reader_api,
            _exact_named(manifest_items, semantic_manifest_name)["id"],
        )
        candidate_market_path = run_root / "03_MARKET_DAY_INDEX" / market_index_name
        if not candidate_market_path.is_file():
            raise RuntimeError(f"CANDIDATE_MARKET_INDEX_MISSING: {market_index_name}")
        candidate_market = json.loads(candidate_market_path.read_text(encoding="utf-8"))
        baseline_market = _download_json(
            reader_api,
            _exact_named(market_items, market_index_name)["id"],
        )

        physical_check = _compare_hashed_file_family(
            candidate=_candidate_files(run_root, "01_ACCESS_SHARDS", stem + "__PHYSICAL_", ".bin"),
            baseline_items=access_items,
            prefix=stem + "__PHYSICAL_",
            suffix=".bin",
        )
        semantic_check = _compare_hashed_file_family(
            candidate=_candidate_files(run_root, "02_SEMANTIC_BUNDLES", stem + "__SEMANTIC_", ".jsonl"),
            baseline_items=semantic_items,
            prefix=stem + "__SEMANTIC_",
            suffix=".jsonl",
        )

        checks = {
            "source_preflight_exact_md5": {"pass": selected.get("status") == "PASS_EXACT_MD5"},
            "source_manifest_stable_fields": {
                "pass": _stable_source(candidate_source_manifest) == _stable_source(baseline_source_manifest),
                "candidate": _stable_source(candidate_source_manifest),
                "baseline": _stable_source(baseline_source_manifest),
            },
            "global_manifest_source_stable_fields": {
                "pass": _stable_source(candidate_global_source) == _stable_source(baseline_global_source),
                "candidate": _stable_source(candidate_global_source),
                "baseline": _stable_source(baseline_global_source),
            },
            "physical_shards_exact_md5": physical_check,
            "semantic_bundles_exact_md5": semantic_check,
            "semantic_bundle_manifest": {
                "pass": candidate_semantic_manifest == baseline_semantic_manifest,
                "candidate_entries": len(candidate_semantic_manifest),
                "baseline_entries": len(baseline_semantic_manifest),
            },
            "market_day_index": {
                "pass": candidate_market == baseline_market,
                "candidate_type": type(candidate_market).__name__,
                "baseline_type": type(baseline_market).__name__,
            },
            "candidate_scope_is_one_source": {
                "pass": len(candidate_global.get("sources", [])) == 1,
                "candidate_sources": len(candidate_global.get("sources", [])),
            },
        }
        parity_pass = all(row.get("pass") is True for row in checks.values())
        report = {
            "pass": parity_pass,
            "gate": "SOURCE_COMPONENT_OF_FULL_DYNAMIC_CORPUS_SHADOW_PARITY",
            "source_index": source_index,
            "source": {
                "name": source_name,
                "drive_id": selected["drive_id"],
                "size": selected.get("drive_size"),
                "drive_md5": selected.get("drive_md5"),
                "canonical_source_count_observed_preflight": preflight.get("canonical_source_count"),
                "source_count_is_not_an_invariant": True,
            },
            "engine": {
                "generation_id": FROZEN_GENERATION_ID,
                "data_plane_impl_version": FROZEN_IMPL_VERSION,
                "semantic_gate": delta_result.get("semantic_gate"),
            },
            "checks": checks,
            "canonical_write_policy": {
                "raw": "READ_ONLY_NEVER_WRITTEN",
                "current": "READ_ONLY_NEVER_WRITTEN",
                "parity_staging": "EVIDENCE_WRITE_ONLY",
            },
        }
        return _persist_source_evidence(
            writer_api,
            run_folder_id=run_folder_id,
            source_index=source_index,
            source_name=source_name,
            candidate_root=run_root,
            report=report,
        )
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def _baseline_stable_map(global_manifest: dict) -> dict[str, dict]:
    return {
        str(row.get("source_drive_id")): {key: row.get(key) for key in STABLE_SOURCE_KEYS}
        for row in global_manifest.get("sources", [])
        if row.get("source_drive_id")
    }


def _candidate_stable_map(checkpoint: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for drive_id, row in checkpoint.get("completed_sources", {}).items():
        stable = row.get("candidate_stable_source")
        if row.get("pass") is True and isinstance(stable, dict):
            out[str(drive_id)] = stable
    return out


def _final_checks(*, checkpoint: dict, preflight: dict, baseline_global: dict) -> dict:
    required_ids = {str(row["drive_id"]) for row in preflight.get("required_sources", [])}
    completed = checkpoint.get("completed_sources", {})
    completed_pass_ids = {
        str(drive_id)
        for drive_id, row in completed.items()
        if row.get("pass") is True
    }
    baseline_map = _baseline_stable_map(baseline_global)
    candidate_map = _candidate_stable_map(checkpoint)
    no_sampling = bool(candidate_map) and all(
        row.get("sampling_used") is False
        and row.get("filtering_used") is False
        and row.get("behavior_labels_created") is False
        for row in candidate_map.values()
    )
    return {
        "dynamic_source_coverage_exact": {
            "pass": completed_pass_ids == required_ids,
            "required_sources": len(required_ids),
            "completed_pass_sources": len(completed_pass_ids),
        },
        "governed_baseline_source_membership_exact": {
            "pass": set(baseline_map) == required_ids,
            "baseline_sources": len(baseline_map),
            "canonical_sources": len(required_ids),
        },
        "all_source_stable_manifests_equal_baseline": {
            "pass": candidate_map == baseline_map,
            "candidate_sources": len(candidate_map),
            "baseline_sources": len(baseline_map),
        },
        "no_sampling_filtering_or_behavior_label_creation": {
            "pass": no_sampling,
            "candidate_sources_checked": len(candidate_map),
        },
        "no_source_holds": {
            "pass": not checkpoint.get("holds"),
            "hold_count": len(checkpoint.get("holds", [])),
        },
    }


def _summary_from_report(report: dict) -> dict:
    checks = report["checks"]
    stable = checks["source_manifest_stable_fields"]["candidate"]
    return {
        "pass": report.get("pass") is True,
        "name": report["source"]["name"],
        "drive_id": report["source"]["drive_id"],
        "candidate_stable_source": stable,
        "physical_shards": checks["physical_shards_exact_md5"].get("candidate_files"),
        "semantic_bundles": checks["semantic_bundles_exact_md5"].get("candidate_files"),
        "semantic_manifest_entries": checks["semantic_bundle_manifest"].get("candidate_entries"),
        "evidence_folder_id": report.get("staging_evidence", {}).get("folder_id"),
        "source_report_file_id": report.get("source_report_upload", {}).get("id"),
    }


def run_full_shadow_parity() -> dict:
    preflight = run_source_preflight()
    if not preflight.get("pass"):
        raise RuntimeError("SOURCE_PREFLIGHT_HOLD: full dynamic source identity did not pass")
    required_sources = list(preflight.get("required_sources", []))
    if not required_sources:
        raise RuntimeError("FULL_SHADOW_EMPTY_CANONICAL_SOURCE_UNIVERSE")

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    _assert_folder(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, PARITY_STAGING_FOLDER_NAME)

    baseline_folders = _baseline_runtime_children(reader_api)
    manifest_items = _list_children(reader_api, baseline_folders["00_MANIFESTS"]["id"])
    access_items = _list_children(reader_api, baseline_folders["01_ACCESS_SHARDS"]["id"])
    semantic_items = _list_children(reader_api, baseline_folders["02_SEMANTIC_BUNDLES"]["id"])
    market_items = _list_children(reader_api, baseline_folders["03_MARKET_DAY_INDEX"]["id"])
    baseline_global = _download_json(
        reader_api,
        _exact_named(manifest_items, "GLOBAL_DATA_PLANE_MANIFEST.json")["id"],
    )

    run_folder_id, run_folder_name, checkpoint, resumed = _find_or_create_run(writer_api, preflight)
    _validate_resume_checkpoint(checkpoint, preflight)

    if checkpoint.get("status") == "PASS":
        final_items = [
            item
            for item in _list_children(writer_api, run_folder_id)
            if item.get("name") == FINAL_REPORT_NAME
        ]
        if len(final_items) != 1:
            raise RuntimeError("FULL_SHADOW_PASS_CHECKPOINT_WITHOUT_UNIQUE_FINAL_REPORT")
        final = _download_json(writer_api, final_items[0]["id"])
        final["already_complete"] = True
        final["resumed_existing_run"] = True
        return final

    completed = dict(checkpoint.get("completed_sources", {}))
    checkpoint["status"] = "IN_PROGRESS"
    checkpoint["holds"] = []

    ordered = sorted(required_sources, key=lambda row: (str(row.get("name")), str(row.get("drive_id"))))
    for index, selected in enumerate(ordered, start=1):
        drive_id = str(selected["drive_id"])
        if completed.get(drive_id, {}).get("pass") is True:
            print(f"RESUME VERIFIED SOURCE {index}/{len(ordered)} | {selected['name']}")
            continue

        checkpoint["current_source"] = selected["name"]
        checkpoint["next_exact_resume_source"] = selected["name"]
        checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
        _persist_checkpoint(writer_api, run_folder_id=run_folder_id, checkpoint=checkpoint)

        print(f"PROCESS SOURCE {index}/{len(ordered)} | {selected['name']}")
        try:
            report = _run_verified_source(
                selected=selected,
                source_index=index,
                preflight=preflight,
                reader_api=reader_api,
                writer_api=writer_api,
                run_folder_id=run_folder_id,
                manifest_items=manifest_items,
                access_items=access_items,
                semantic_items=semantic_items,
                market_items=market_items,
                baseline_global=baseline_global,
            )
            if not report.get("pass"):
                raise RuntimeError(f"SOURCE_PARITY_HOLD: {selected['name']}")
            completed[drive_id] = _summary_from_report(report)
            checkpoint["completed_sources"] = completed
            checkpoint["current_source"] = None
            next_name = ordered[index]["name"] if index < len(ordered) else None
            checkpoint["next_exact_resume_source"] = next_name
            checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
            _persist_checkpoint(writer_api, run_folder_id=run_folder_id, checkpoint=checkpoint)
            print(
                f"SOURCE PASS {index}/{len(ordered)} | {selected['name']} | "
                f"physical={completed[drive_id]['physical_shards']} | semantic={completed[drive_id]['semantic_bundles']}"
            )
        except Exception as exc:
            checkpoint["completed_sources"] = completed
            checkpoint["status"] = "HOLD"
            checkpoint["current_source"] = selected["name"]
            checkpoint["next_exact_resume_source"] = selected["name"]
            checkpoint.setdefault("holds", []).append(
                {
                    "source": selected["name"],
                    "reason": f"{type(exc).__name__}: {exc}",
                    "at_utc": datetime.now(timezone.utc).isoformat(),
                }
            )
            checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
            checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
            _persist_checkpoint(writer_api, run_folder_id=run_folder_id, checkpoint=checkpoint)
            raise

    checkpoint["completed_sources"] = completed
    checkpoint["current_source"] = None
    checkpoint["next_exact_resume_source"] = None
    checkpoint["holds"] = []
    final_checks = _final_checks(
        checkpoint=checkpoint,
        preflight=preflight,
        baseline_global=baseline_global,
    )
    final_pass = all(row.get("pass") is True for row in final_checks.values())
    report = {
        "pass": final_pass,
        "gate": FULL_SHADOW_GATE,
        "scope": "COMPLETE_DYNAMIC_CANONICAL_SOURCE_UNIVERSE_SOURCE_ISOLATED_SHADOW_REPRODUCTION",
        "run_folder_id": run_folder_id,
        "run_folder_name": run_folder_name,
        "resumed_existing_run": resumed,
        "github_sha": _github_sha(),
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": _source_universe_fingerprint(preflight),
        "canonical_source_count_observed": len(ordered),
        "source_count_is_not_an_invariant": True,
        "completed_source_count": len(completed),
        "checks": final_checks,
        "source_summaries": [completed[str(row["drive_id"])] for row in ordered],
        "canonical_write_policy": {
            "raw": "READ_ONLY_NEVER_WRITTEN",
            "current": "READ_ONLY_NEVER_WRITTEN",
            "parity_staging": "CHECKPOINT_AND_RECONCILIATION_EVIDENCE_ONLY",
        },
        "execution_model": {
            "scratch": "BOUNDED_ONE_SOURCE_AT_A_TIME_EPHEMERAL_WINDOWS_SCRATCH",
            "resume": "DRIVE_PERSISTED_SOURCE_BOUNDARY_CHECKPOINTS",
            "sampling": False,
            "fixed_source_count": False,
            "note": "This gate proves every dynamically discovered canonical source and its governed source-scoped derivatives against CURRENT. Persistent multi-source delta-state transition parity is a separate later gate.",
        },
    }
    final_upload = _upload_json(
        writer_api,
        parent_id=run_folder_id,
        name=FINAL_REPORT_NAME,
        payload=report,
    )
    report["final_report_upload"] = final_upload
    report["pass"] = report["pass"] and final_upload.get("pass") is True

    checkpoint["status"] = "PASS" if report["pass"] else "HOLD"
    checkpoint["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    checkpoint["checkpoint_sequence"] = int(checkpoint.get("checkpoint_sequence", 0)) + 1
    if not report["pass"]:
        checkpoint["holds"] = [
            {
                "source": None,
                "reason": "FULL_SHADOW_FINAL_RECONCILIATION_HOLD",
                "at_utc": datetime.now(timezone.utc).isoformat(),
            }
        ]
    _persist_checkpoint(writer_api, run_folder_id=run_folder_id, checkpoint=checkpoint)
    return report
