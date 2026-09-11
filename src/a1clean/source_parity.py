from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

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
from .source_preflight import run_source_preflight

FOLDER_MIME = "application/vnd.google-apps.folder"
BASELINE_RUNTIME_FOLDERS = (
    "00_MANIFESTS",
    "01_ACCESS_SHARDS",
    "02_SEMANTIC_BUNDLES",
    "03_MARKET_DAY_INDEX",
    "04_SEMANTIC_EVENT_CONTRACT",
)


def _list_children(api, parent_id: str, *, fields: str = "id,name,mimeType,size,md5Checksum") -> list[dict]:
    out: list[dict] = []
    token = None
    while True:
        response = (
            api.files()
            .list(
                q=f"'{parent_id}' in parents and trashed=false",
                fields=f"nextPageToken,files({fields})",
                pageSize=1000,
                pageToken=token,
                orderBy="name",
            )
            .execute()
        )
        out.extend(response.get("files", []))
        token = response.get("nextPageToken")
        if not token:
            return out


def _folder_snapshot(api, folder_id: str) -> dict:
    return (
        api.files()
        .get(fileId=folder_id, fields="id,name,mimeType,parents", supportsAllDrives=True)
        .execute()
    )


def _assert_folder(api, folder_id: str, expected_name: str) -> dict:
    item = _folder_snapshot(api, folder_id)
    if item.get("name") != expected_name or item.get("mimeType") != FOLDER_MIME:
        raise RuntimeError(
            f"GOVERNED_FOLDER_IDENTITY_MISMATCH: expected={expected_name!r} "
            f"actual={item.get('name')!r} id={folder_id}"
        )
    return item


def _download_bytes(api, file_id: str) -> bytes:
    request = api.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def _download_json(api, file_id: str) -> Any:
    return json.loads(_download_bytes(api, file_id).decode("utf-8"))


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stable_source(obj: dict) -> dict:
    return {key: obj.get(key) for key in STABLE_SOURCE_KEYS}


def _single_source_from_global(global_manifest: dict, source_drive_id: str) -> dict:
    matches = [
        row
        for row in global_manifest.get("sources", [])
        if row.get("source_drive_id") == source_drive_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"GLOBAL_MANIFEST_SOURCE_CARDINALITY: source_drive_id={source_drive_id} matches={len(matches)}"
        )
    return matches[0]


def _exact_named(items: list[dict], name: str) -> dict:
    matches = [item for item in items if item.get("name") == name]
    if len(matches) != 1:
        raise RuntimeError(f"BASELINE_FILE_CARDINALITY: name={name!r} matches={len(matches)}")
    return matches[0]


def _baseline_runtime_children(reader_api) -> dict[str, dict]:
    _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    children = _list_children(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID)
    folders = {
        item.get("name"): item
        for item in children
        if item.get("mimeType") == FOLDER_MIME
    }
    missing = [name for name in BASELINE_RUNTIME_FOLDERS if name not in folders]
    if missing:
        raise RuntimeError(f"BASELINE_RUNTIME_FOLDER_MISSING: {missing}")
    return folders


class _StaticListRequest:
    def __init__(self, selected_metadata: dict):
        self._selected_metadata = dict(selected_metadata)

    def execute(self):
        # Full dynamic membership was already proven by source-preflight. The frozen engine
        # receives one exact canonical metadata snapshot only for this technical parity gate.
        return {"files": [dict(self._selected_metadata)], "nextPageToken": None}


class _ScopedFiles:
    def __init__(self, files_resource, selected_metadata: dict):
        self._files = files_resource
        self._selected_metadata = dict(selected_metadata)

    def list(self, *args, **kwargs):
        return _StaticListRequest(self._selected_metadata)

    def __getattr__(self, name: str):
        return getattr(self._files, name)


class _SingleSourceDriveApi:
    """Read-only Drive proxy exposing one already-verified canonical source to frozen V2."""

    def __init__(self, reader_api, selected_metadata: dict):
        self._reader_api = reader_api
        self._selected_metadata = dict(selected_metadata)

    def files(self):
        return _ScopedFiles(self._reader_api.files(), self._selected_metadata)


def _candidate_files(root: Path, folder: str, prefix: str, suffix: str) -> dict[str, Path]:
    base = root / folder
    if not base.exists():
        return {}
    return {
        path.name: path
        for path in sorted(base.iterdir())
        if path.is_file() and path.name.startswith(prefix) and path.name.endswith(suffix)
    }


def _compare_hashed_file_family(
    *,
    candidate: dict[str, Path],
    baseline_items: list[dict],
    prefix: str,
    suffix: str,
) -> dict:
    baseline = {
        item["name"]: item
        for item in baseline_items
        if item.get("mimeType") != FOLDER_MIME
        and item.get("name", "").startswith(prefix)
        and item.get("name", "").endswith(suffix)
    }
    names = sorted(set(candidate) | set(baseline))
    evidence = []
    all_pass = True
    for name in names:
        local = candidate.get(name)
        remote = baseline.get(name)
        candidate_md5 = _md5(local) if local else None
        candidate_size = local.stat().st_size if local else None
        baseline_md5 = remote.get("md5Checksum") if remote else None
        baseline_size = int(remote["size"]) if remote and remote.get("size") is not None else None
        row_pass = (
            local is not None
            and remote is not None
            and baseline_md5 is not None
            and candidate_md5 == baseline_md5
            and candidate_size == baseline_size
        )
        all_pass = all_pass and row_pass
        evidence.append(
            {
                "name": name,
                "pass": row_pass,
                "candidate_size": candidate_size,
                "baseline_size": baseline_size,
                "candidate_md5": candidate_md5,
                "baseline_md5": baseline_md5,
            }
        )
    return {
        "pass": all_pass and bool(names),
        "candidate_files": len(candidate),
        "baseline_files": len(baseline),
        "files": evidence,
    }


def _find_candidate_manifest(manifest_dir: Path, exact_name: str) -> Path:
    path = manifest_dir / exact_name
    if not path.is_file():
        raise RuntimeError(f"CANDIDATE_MANIFEST_MISSING: {exact_name}")
    return path


def _create_folder(writer_api, *, parent_id: str, name: str) -> str:
    created = (
        writer_api.files()
        .create(
            body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]},
            fields="id,name,parents",
            supportsAllDrives=True,
        )
        .execute()
    )
    folder_id = created.get("id")
    if not folder_id or parent_id not in (created.get("parents") or []):
        raise RuntimeError(f"STAGING_FOLDER_CREATE_RECONCILIATION_FAILED: {name}")
    return folder_id


def _upload_file(writer_api, *, parent_id: str, source: Path, target_name: str | None = None) -> dict:
    media = MediaFileUpload(str(source), resumable=True)
    created = (
        writer_api.files()
        .create(
            body={"name": target_name or source.name, "parents": [parent_id]},
            media_body=media,
            fields="id,name,size,md5Checksum,parents",
            supportsAllDrives=True,
        )
        .execute()
    )
    expected_md5 = _md5(source)
    actual_md5 = created.get("md5Checksum")
    parent_ok = parent_id in (created.get("parents") or [])
    size_ok = int(created.get("size", -1)) == source.stat().st_size
    md5_ok = actual_md5 == expected_md5
    return {
        "pass": bool(created.get("id")) and parent_ok and size_ok and md5_ok,
        "id": created.get("id"),
        "name": created.get("name"),
        "size": int(created.get("size", -1)),
        "md5": actual_md5,
        "expected_md5": expected_md5,
        "parent_ok": parent_ok,
    }


def _safe_slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value[:80] or "source"


def _persist_evidence(
    writer_api,
    *,
    candidate_root: Path,
    source_name: str,
    pass_state: bool,
) -> dict:
    _assert_folder(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, PARITY_STAGING_FOLDER_NAME)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder_name = f"SOURCE_PARITY_{stamp}_{'PASS' if pass_state else 'HOLD'}_{_safe_slug(Path(source_name).stem)}"
    run_folder_id = _create_folder(
        writer_api, parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, name=folder_name
    )

    manifest_dir = candidate_root / "00_MANIFESTS"
    stem = Path(source_name).stem
    evidence_paths: list[Path] = []
    for path in sorted(manifest_dir.iterdir() if manifest_dir.exists() else []):
        if path.is_file() and (
            path.name.startswith(source_name)
            or path.name.startswith(stem)
            or path.name
            in {
                "GLOBAL_DATA_PLANE_MANIFEST.json",
                "GLOBAL_SOURCE_DISCOVERY.json",
                "LATEST_DELTA_REFRESH.json",
            }
        ):
            evidence_paths.append(path)
    market_index = candidate_root / "03_MARKET_DAY_INDEX" / f"{stem}__MARKET_DAY_INDEX.json"
    if market_index.is_file():
        evidence_paths.append(market_index)

    uploads = []
    seen: set[Path] = set()
    for path in evidence_paths:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        uploads.append(
            _upload_file(
                writer_api,
                parent_id=run_folder_id,
                source=path,
                target_name="CANDIDATE__" + path.name,
            )
        )
    return {
        "pass": all(row.get("pass") is True for row in uploads) and bool(uploads),
        "folder_id": run_folder_id,
        "folder_name": folder_name,
        "uploads": uploads,
        "final_report_target_name": "PARITY_REPORT_FINAL.json",
        "persistence_mode": "HASH_EVIDENCE_ONLY_SOURCE_SCOPE_TECHNICAL_GATE",
        "note": (
            "Physical and semantic candidate bodies were compared byte-for-byte by MD5 against the governed baseline, "
            "then deleted locally after this run. This source-scoped gate persists reconciliation evidence/manifests only; "
            "it is not full-corpus staging parity evidence."
        ),
    }


def run_source_scoped_parity(source_name: str) -> dict:
    """Run one-source frozen-V2 parity as a governed technical migration gate.

    The canonical source universe remains dynamic. This function deliberately scopes one already-verified
    canonical source only to validate Windows execution equivalence before any full-corpus shadow run.
    It never writes canonical RAW or governed CURRENT.
    """
    source_name = source_name.strip()
    if not source_name:
        raise ValueError("source_name is required")

    preflight = run_source_preflight()
    if not preflight.get("pass"):
        raise RuntimeError("SOURCE_PREFLIGHT_HOLD: full dynamic source identity did not pass")
    selected = [row for row in preflight.get("required_sources", []) if row.get("name") == source_name]
    if len(selected) != 1:
        raise RuntimeError(
            f"SOURCE_NOT_UNIQUELY_CANONICAL: source_name={source_name!r} matches={len(selected)}"
        )
    selected = selected[0]
    if selected.get("status") != "PASS_EXACT_MD5":
        raise RuntimeError(f"SOURCE_IDENTITY_NOT_EXACT: {selected.get('status')}")

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    _assert_folder(reader_api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    _assert_folder(writer_api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID, PARITY_STAGING_FOLDER_NAME)

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
        raise RuntimeError("SOURCE_METADATA_NAME_DRIFT")
    if int(source_meta.get("size", -1)) != int(selected.get("drive_size", -2)):
        raise RuntimeError("SOURCE_METADATA_SIZE_DRIFT")
    if source_meta.get("md5Checksum") != selected.get("drive_md5"):
        raise RuntimeError("SOURCE_METADATA_MD5_DRIFT")

    temp_parent = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()).resolve()
    run_root = Path(tempfile.mkdtemp(prefix="a1-source-parity-", dir=str(temp_parent))).resolve()
    scratch = run_root / "_scratch"
    report_path = run_root / "SOURCE_PARITY_REPORT.json"
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
        scoped_drive = _SingleSourceDriveApi(reader_api, source_meta)
        delta_result = run_delta(config, scoped_drive)

        baseline_folders = _baseline_runtime_children(reader_api)
        manifest_items = _list_children(reader_api, baseline_folders["00_MANIFESTS"]["id"])
        access_items = _list_children(reader_api, baseline_folders["01_ACCESS_SHARDS"]["id"])
        semantic_items = _list_children(reader_api, baseline_folders["02_SEMANTIC_BUNDLES"]["id"])
        market_items = _list_children(reader_api, baseline_folders["03_MARKET_DAY_INDEX"]["id"])

        stem = Path(source_name).stem
        source_manifest_name = f"{source_name}__DATA_PLANE_MANIFEST.json"
        semantic_manifest_name = f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
        market_index_name = f"{stem}__MARKET_DAY_INDEX.json"
        candidate_manifest_dir = run_root / "00_MANIFESTS"

        candidate_source_manifest = json.loads(
            _find_candidate_manifest(candidate_manifest_dir, source_manifest_name).read_text(encoding="utf-8")
        )
        baseline_source_manifest_item = _exact_named(manifest_items, source_manifest_name)
        baseline_source_manifest = _download_json(reader_api, baseline_source_manifest_item["id"])

        candidate_global = json.loads(
            _find_candidate_manifest(candidate_manifest_dir, "GLOBAL_DATA_PLANE_MANIFEST.json").read_text(
                encoding="utf-8"
            )
        )
        baseline_global_item = _exact_named(manifest_items, "GLOBAL_DATA_PLANE_MANIFEST.json")
        baseline_global = _download_json(reader_api, baseline_global_item["id"])
        candidate_global_source = _single_source_from_global(candidate_global, selected["drive_id"])
        baseline_global_source = _single_source_from_global(baseline_global, selected["drive_id"])

        candidate_semantic_manifest = json.loads(
            _find_candidate_manifest(candidate_manifest_dir, semantic_manifest_name).read_text(encoding="utf-8")
        )
        baseline_semantic_manifest = _download_json(
            reader_api, _exact_named(manifest_items, semantic_manifest_name)["id"]
        )

        candidate_market_path = run_root / "03_MARKET_DAY_INDEX" / market_index_name
        if not candidate_market_path.is_file():
            raise RuntimeError(f"CANDIDATE_MARKET_INDEX_MISSING: {market_index_name}")
        candidate_market = json.loads(candidate_market_path.read_text(encoding="utf-8"))
        baseline_market = _download_json(reader_api, _exact_named(market_items, market_index_name)["id"])

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
            "gate": "SOURCE_SCOPED_WINDOWS_FROZEN_V2_PARITY_TECHNICAL_GATE",
            "scope": "ONE_CANONICAL_SOURCE_ONLY_NOT_FULL_CORPUS_PARITY",
            "source": {
                "name": source_name,
                "drive_id": selected["drive_id"],
                "size": selected.get("drive_size"),
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

        persisted = _persist_evidence(
            writer_api,
            candidate_root=run_root,
            source_name=source_name,
            pass_state=parity_pass,
        )
        report["staging_evidence"] = persisted
        report["pass"] = parity_pass and persisted.get("pass") is True
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        final_report_upload = _upload_file(
            writer_api,
            parent_id=persisted["folder_id"],
            source=report_path,
            target_name=persisted["final_report_target_name"],
        )
        report["final_report_upload"] = final_report_upload
        report["pass"] = report["pass"] and final_report_upload.get("pass") is True
        return report
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
