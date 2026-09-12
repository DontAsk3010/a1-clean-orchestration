from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    FROZEN_RAW_FOLDER_DRIVE_ID,
    DataPlaneConfig,
)
from .frozen_v2 import run_delta
from .source_parity import (
    _SingleSourceDriveApi,
    _baseline_runtime_children,
    _create_folder,
    _download_json,
    _exact_named,
    _list_children,
    _safe_slug,
    _upload_file,
)

CONTROL_FILE_NAMES = (
    "GLOBAL_DATA_PLANE_MANIFEST.json",
    "GLOBAL_SOURCE_DISCOVERY.json",
    "GLOBAL_SOURCE_COVERAGE_INDEX.json",
    "PERSISTENT_SOURCE_STATE.json",
    "LATEST_DELTA_REFRESH.json",
    "AI_SEMANTIC_DELTA_QUEUE.json",
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def upload_json_payload(writer_api, *, parent_id: str, name: str, payload: dict) -> dict:
    temp_root = Path(tempfile.mkdtemp(prefix="a1-delta-json-"))
    try:
        path = temp_root / name
        write_json(path, payload)
        return _upload_file(writer_api, parent_id=parent_id, source=path, target_name=name)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def baseline_controls(reader_api) -> tuple[dict, dict, dict]:
    folders = _baseline_runtime_children(reader_api)
    manifest_items = _list_children(reader_api, folders["00_MANIFESTS"]["id"])
    global_manifest = _download_json(
        reader_api,
        _exact_named(manifest_items, "GLOBAL_DATA_PLANE_MANIFEST.json")["id"],
    )
    persistent_state = _download_json(
        reader_api,
        _exact_named(manifest_items, "PERSISTENT_SOURCE_STATE.json")["id"],
    )
    return folders, global_manifest, persistent_state


def _source_metadata(reader_api, selected: dict) -> dict:
    metadata = (
        reader_api.files()
        .get(
            fileId=selected["drive_id"],
            fields="id,name,mimeType,size,modifiedTime,parents,md5Checksum",
            supportsAllDrives=True,
        )
        .execute()
    )
    if metadata.get("name") != selected.get("name"):
        raise RuntimeError(f"SOURCE_METADATA_NAME_DRIFT: {selected.get('name')}")
    if int(metadata.get("size", -1)) != int(selected.get("drive_size", -2)):
        raise RuntimeError(f"SOURCE_METADATA_SIZE_DRIFT: {selected.get('name')}")
    if metadata.get("md5Checksum") != selected.get("drive_md5"):
        raise RuntimeError(f"SOURCE_METADATA_MD5_DRIFT: {selected.get('name')}")
    return metadata


def process_source_to_local(*, selected: dict, reader_api) -> tuple[Path, dict, dict]:
    metadata = _source_metadata(reader_api, selected)
    temp_parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()).resolve()
    root = Path(tempfile.mkdtemp(prefix="a1-governed-delta-source-", dir=str(temp_parent))).resolve()
    scratch = root / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    config = DataPlaneConfig(
        engine_root=root,
        raw_dir=Path(os.environ["A1_RAW_DIR"]).expanduser().resolve(),
        runtime_ingest_dir=root,
        raw_folder_drive_id=FROZEN_RAW_FOLDER_DRIVE_ID,
        current_folder_drive_id=FROZEN_CURRENT_FOLDER_DRIVE_ID,
        parity_staging_folder_drive_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        run_root=root,
        scratch_dir=scratch,
        generation_id=FROZEN_GENERATION_ID,
        data_plane_impl_version=FROZEN_IMPL_VERSION,
    )
    try:
        result = run_delta(config, _SingleSourceDriveApi(reader_api, metadata))
        stem = Path(selected["name"]).stem
        manifest_path = root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"PROCESSED_SOURCE_MANIFEST_MISSING: {selected['name']}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return root, result, manifest
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _source_artifact_paths(root: Path, source_name: str) -> dict[str, list[Path]]:
    stem = Path(source_name).stem
    manifest_dir = root / "00_MANIFESTS"
    market = root / "03_MARKET_DAY_INDEX" / f"{stem}__MARKET_DAY_INDEX.json"
    return {
        "00_MANIFESTS": [
            path
            for path in (
                manifest_dir / f"{stem}__DATA_PLANE_MANIFEST.json",
                manifest_dir / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json",
            )
            if path.is_file()
        ],
        "01_ACCESS_SHARDS": sorted((root / "01_ACCESS_SHARDS").glob(f"{stem}__PHYSICAL_*.bin")),
        "02_SEMANTIC_BUNDLES": sorted((root / "02_SEMANTIC_BUNDLES").glob(f"{stem}__SEMANTIC_*.jsonl")),
        "03_MARKET_DAY_INDEX": [market] if market.is_file() else [],
    }


def persist_processed_source(
    writer_api,
    *,
    sources_folder_id: str,
    source_index: int,
    source_name: str,
    root: Path,
    engine_result: dict,
    source_manifest: dict,
    delta_action: str,
    stamp: str,
) -> dict:
    folder_name = f"SRC_{source_index:04d}_{_safe_slug(Path(source_name).stem)}_{stamp}"
    folder_id = _create_folder(writer_api, parent_id=sources_folder_id, name=folder_name)
    uploads: list[dict] = []
    artifact_folders: dict[str, str] = {}
    for logical_folder, paths in _source_artifact_paths(root, source_name).items():
        child_id = _create_folder(writer_api, parent_id=folder_id, name=logical_folder)
        artifact_folders[logical_folder] = child_id
        for path in paths:
            uploads.append({
                "logical_folder": logical_folder,
                **_upload_file(writer_api, parent_id=child_id, source=path, target_name=path.name),
            })
    required = {"00_MANIFESTS", "01_ACCESS_SHARDS", "02_SEMANTIC_BUNDLES", "03_MARKET_DAY_INDEX"}
    passed_families = {row["logical_folder"] for row in uploads if row.get("pass") is True}
    passed = required.issubset(passed_families) and bool(uploads) and all(row.get("pass") is True for row in uploads)
    return {
        "pass": passed,
        "source_name": source_name,
        "source_drive_id": source_manifest.get("source_drive_id"),
        "source_sha256": source_manifest.get("source_sha256"),
        "source_manifest": source_manifest,
        "semantic_gate": engine_result.get("semantic_gate"),
        "delta_action": delta_action,
        "staging_folder_id": folder_id,
        "staging_folder_name": folder_name,
        "artifact_folders": artifact_folders,
        "upload_count": len(uploads),
    }


def persist_control_bundle(writer_api, *, run_folder_id: str, bundle: dict, stamp: str) -> dict:
    folder_id = _create_folder(writer_api, parent_id=run_folder_id, name=f"CONTROL_BUNDLE_{stamp}")
    uploads = []
    temp_root = Path(tempfile.mkdtemp(prefix="a1-delta-control-"))
    try:
        for name in CONTROL_FILE_NAMES:
            path = temp_root / name
            write_json(path, bundle[name])
            uploads.append({"name": name, **_upload_file(writer_api, parent_id=folder_id, source=path, target_name=name)})
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return {
        "pass": bool(uploads) and all(row.get("pass") is True for row in uploads),
        "folder_id": folder_id,
        "uploads": uploads,
    }
