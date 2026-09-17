from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from googleapiclient.http import MediaIoBaseDownload

from ..config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
    FROZEN_RAW_FOLDER_DRIVE_ID,
    DataPlaneConfig,
)
from ..frozen_v2 import run_delta
from ..google_drive import build_drive_api
from ..pattern_discovery.packet import parse_semantic_packet
from ..source_parity import FOLDER_MIME, _SingleSourceDriveApi, _assert_folder, _list_children
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .formula_replay import packet_to_formula_bars

MARCH_2025_SOURCE = v11.RESERVED_OOS

LEGACY_SOURCE_NAMES = tuple(v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B)
FULL_CHRONOLOGICAL_SOURCE_NAMES = (
    v11.DISCOVERY[0],
    v11.DISCOVERY[1],
    v11.DISCOVERY[2],
    MARCH_2025_SOURCE,
    *v11.DISCOVERY[3:],
    *v11.VALIDATION_A,
    *v11.VALIDATION_B,
)

EXPECTED_LEGACY_SOURCE_COUNT = 17
EXPECTED_FULL_SOURCE_COUNT = 18
EXPECTED_LEGACY_TICKER_DAYS = 298_483
EXPECTED_LEGACY_MINUTE_ROWS = 32_350_174

SOURCE_ENVELOPES: dict[str, tuple[str, str]] = {
    "Raw Des 02-31-2024.csv": ("2024-12-02", "2024-12-31"),
    "Raw Jan 01-31-2025.csv": ("2025-01-01", "2025-01-31"),
    "Raw Feb 03-28-2025.csv": ("2025-02-03", "2025-02-28"),
    "Raw Maret 03-31-2025.csv": ("2025-03-03", "2025-03-31"),
    "Raw April 01-30-2025.csv": ("2025-04-01", "2025-04-30"),
    "Raw Mei 01-30-2025.csv": ("2025-05-01", "2025-05-30"),
    "Raw Juni 02-30-2025.csv": ("2025-06-02", "2025-06-30"),
    "Raw Juli 01-31-2025.csv": ("2025-07-01", "2025-07-31"),
    "Raw Agust 01-29-2025.csv": ("2025-08-01", "2025-08-29"),
    "Raw Sep 01-30-2025.csv": ("2025-09-01", "2025-09-30"),
    "Raw Oct 01-31-2025.csv": ("2025-10-01", "2025-10-31"),
    "Raw Nov 03-29-2025.csv": ("2025-11-03", "2025-11-29"),
    "Raw Des 01-31-2025.csv": ("2025-12-01", "2025-12-31"),
    "Raw Jan 01-30-2026.csv": ("2026-01-01", "2026-01-30"),
    "Raw Feb 02-27-2026.csv": ("2026-02-02", "2026-02-27"),
    "Raw Mar 02-31-2026.csv": ("2026-03-02", "2026-03-31"),
    "Raw Apr 01-30-2026.csv": ("2026-04-01", "2026-04-30"),
    "Raw Mei 01-29-2026.csv": ("2026-05-01", "2026-05-29"),
}


def _sha(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _hash_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> tuple[str, str]:
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def _assert_chronology(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != EXPECTED_FULL_SOURCE_COUNT:
        raise RuntimeError(f"V31_SOURCE_COUNT_MISMATCH:{len(rows)}")
    names = [str(x["source_name"]) for x in rows]
    if tuple(names) != FULL_CHRONOLOGICAL_SOURCE_NAMES:
        raise RuntimeError("V31_SOURCE_ORDER_MISMATCH")
    for prev, cur in zip(rows, rows[1:]):
        if str(prev["last_date"]) >= str(cur["first_date"]):
            raise RuntimeError(
                f"V31_SOURCE_DATE_OVERLAP_OR_REVERSE:{prev['source_name']}:{prev['last_date']}:"
                f"{cur['source_name']}:{cur['first_date']}"
            )

    feb = rows[2]
    march = rows[3]
    april = rows[4]
    if str(feb["source_name"]) != "Raw Feb 03-28-2025.csv":
        raise RuntimeError("V31_FEB_SOURCE_POSITION_MISMATCH")
    if str(march["source_name"]) != MARCH_2025_SOURCE:
        raise RuntimeError("V31_MARCH_SOURCE_POSITION_MISMATCH")
    if str(april["source_name"]) != "Raw April 01-30-2025.csv":
        raise RuntimeError("V31_APRIL_SOURCE_POSITION_MISMATCH")
    if not (
        str(feb["last_date"])
        < str(march["first_date"])
        <= str(march["last_date"])
        < str(april["first_date"])
    ):
        raise RuntimeError("V31_FEB_MARCH_APRIL_CHRONOLOGY_FAIL")

    return {
        "february_source": str(feb["source_name"]),
        "february_last_date": str(feb["last_date"]),
        "march_source": str(march["source_name"]),
        "march_first_date": str(march["first_date"]),
        "march_last_date": str(march["last_date"]),
        "april_source": str(april["source_name"]),
        "april_first_date": str(april["first_date"]),
        "feb_march_april_order_pass": True,
    }


def _canonical_raw_items(api) -> dict[str, dict[str, Any]]:
    _assert_folder(api, FROZEN_RAW_FOLDER_DRIVE_ID, "02_CURRENT_HISTORICAL_RAW_DATA_UJI")
    children = _list_children(
        api,
        FROZEN_RAW_FOLDER_DRIVE_ID,
        fields="id,name,mimeType,size,md5Checksum,modifiedTime",
    )
    by_name: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for item in children:
        if item.get("mimeType") == FOLDER_MIME:
            continue
        name = str(item.get("name") or "")
        if name in by_name:
            duplicates.append(name)
        by_name[name] = dict(item)
    if duplicates:
        raise RuntimeError(f"V31_CANONICAL_RAW_DUPLICATE_NAMES:{sorted(set(duplicates))}")
    missing = [name for name in FULL_CHRONOLOGICAL_SOURCE_NAMES if name not in by_name]
    if missing:
        raise RuntimeError(f"V31_CANONICAL_RAW_REQUIRED_SOURCE_MISSING:{missing}")
    return {name: by_name[name] for name in FULL_CHRONOLOGICAL_SOURCE_NAMES}


def _legacy_cache_source(source: str, raw_item: Mapping[str, Any]) -> dict[str, Any]:
    meta_path = v12r._meta_path(source)
    cache_path = v12r._cache_path(source)
    if not meta_path.is_file() or not cache_path.is_file():
        raise RuntimeError(f"V31_LEGACY_CACHE_MISSING:{source}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if (
        meta.get("schema") != v12r.CACHE_SCHEMA
        or meta.get("source_name") != source
        or meta.get("complete") is not True
        or int(meta.get("cached_ticker_days", -1)) != int(meta.get("ticker_days", -2))
        or int(meta.get("ticker_days", -1)) < 0
        or int(meta.get("rows", -1)) < 0
    ):
        raise RuntimeError(f"V31_LEGACY_CACHE_INVALID:{source}")
    if meta.get("cached_session_rows") is not None and int(meta["cached_session_rows"]) != int(meta["rows"]):
        raise RuntimeError(
            f"V31_LEGACY_CACHE_ROW_SEMANTICS_DRIFT:{source}:"
            f"{meta['cached_session_rows']}!={meta['rows']}"
        )
    baseline_id = str(meta.get("source_drive_id") or "")
    current_id = str(raw_item.get("id") or "")
    if not baseline_id or baseline_id != current_id:
        raise RuntimeError(
            f"V31_LEGACY_CURRENT_RAW_IDENTITY_DRIFT:{source}:BASELINE={baseline_id}:CURRENT={current_id}"
        )
    first_date, last_date = SOURCE_ENVELOPES[source]
    return {
        "source_name": source,
        "first_date": first_date,
        "last_date": last_date,
        "ticker_days": int(meta["ticker_days"]),
        "rows": int(meta["rows"]),
        "source_drive_id": baseline_id,
        "source_sha256": meta.get("source_sha256"),
        "generation_id": meta.get("generation_id"),
        "semantic_manifest_fingerprint": meta.get("semantic_manifest_fingerprint"),
        "cache_schema": meta.get("schema"),
        "cache_complete": True,
        "cache_path": str(cache_path),
        "meta_path": str(meta_path),
        "legacy_v2_source": True,
        "march_2025_catchup_source": False,
        "current_raw_drive_id": current_id,
        "current_raw_size": int(raw_item["size"]) if raw_item.get("size") is not None else None,
        "current_raw_md5": raw_item.get("md5Checksum"),
        "source_identity_mode": "FROZEN_V2_CACHE_EXACT_CURRENT_RAW_ID",
    }


def _download_raw_to_stage(api, item: Mapping[str, Any], source: str) -> tuple[Path, str]:
    drive_id = str(item["id"])
    root = Path.home() / ".a1clean" / "v31_raw_stage" / drive_id
    root.mkdir(parents=True, exist_ok=True)
    target = root / source
    expected_size = int(item.get("size") or -1)
    expected_md5 = str(item.get("md5Checksum") or "").lower()

    def exact(path: Path) -> bool:
        if not path.is_file() or expected_size < 0 or path.stat().st_size != expected_size:
            return False
        if not expected_md5:
            return False
        actual_md5, _ = _hash_file(path)
        return actual_md5.lower() == expected_md5

    if exact(target):
        return target, "REUSED_DURABLE_V31_RAW_STAGE"

    partial = target.with_suffix(target.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    request = api.files().get_media(fileId=drive_id, supportsAllDrives=True)
    with partial.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    if not exact(partial):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"V31_MARCH_RAW_DOWNLOAD_IDENTITY_FAIL:{source}")
    partial.replace(target)
    return target, "DOWNLOADED_CURRENT_CANONICAL_RAW_TO_V31_STAGE"


def _resolve_march_raw_dir(api, item: Mapping[str, Any]) -> tuple[Path, str]:
    configured = os.environ.get("A1_RAW_DIR")
    expected_size = int(item.get("size") or -1)
    expected_md5 = str(item.get("md5Checksum") or "").lower()
    if configured:
        candidate = Path(configured).expanduser().resolve() / MARCH_2025_SOURCE
        if candidate.is_file() and candidate.stat().st_size == expected_size and expected_md5:
            actual_md5, _ = _hash_file(candidate)
            if actual_md5.lower() == expected_md5:
                return candidate.parent, "REUSED_LOCAL_CANONICAL_RAW_EXACT_MD5"
    staged, mode = _download_raw_to_stage(api, item, MARCH_2025_SOURCE)
    return staged.parent, mode


def _validate_local_candidate(root: Path, raw_item: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], bytes] | None:
    stem = Path(MARCH_2025_SOURCE).stem
    data_path = root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json"
    sem_path = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    if not data_path.is_file() or not sem_path.is_file():
        return None
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
        sem_bytes = sem_path.read_bytes()
        sem = json.loads(sem_bytes.decode("utf-8"))
    except Exception:
        return None
    if (
        data.get("status") != "ACCESS_READY_FOR_AI"
        or data.get("source_name") != MARCH_2025_SOURCE
        or str(data.get("source_drive_id") or "") != str(raw_item.get("id") or "")
        or not isinstance(sem, list)
        or not sem
        or len(sem) != int(data.get("ticker_day_objects") or -1)
        or sum(int(x.get("data_row_count") or 0) for x in sem)
        != int(data.get("source_data_rows") or -1)
    ):
        return None
    return data, sem, sem_bytes


def _ensure_march_data_plane(api, raw_item: Mapping[str, Any]) -> tuple[Path, dict[str, Any], list[dict[str, Any]], bytes, str]:
    remote_md5 = str(raw_item.get("md5Checksum") or "NO_MD5")
    key = hashlib.sha256(
        (str(raw_item.get("id")) + "|" + remote_md5 + "|" + str(raw_item.get("size"))).encode("utf-8")
    ).hexdigest()[:24]
    root = Path.home() / ".a1clean" / "v31_march_data_plane" / key
    existing = _validate_local_candidate(root, raw_item)
    if existing is not None:
        data, sem, sem_bytes = existing
        return root, data, sem, sem_bytes, "REUSED_V31_MARCH_DATA_PLANE"

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    raw_dir, raw_access_mode = _resolve_march_raw_dir(api, raw_item)
    scratch = root / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    config = DataPlaneConfig(
        engine_root=root,
        raw_dir=raw_dir,
        runtime_ingest_dir=root,
        raw_folder_drive_id=FROZEN_RAW_FOLDER_DRIVE_ID,
        current_folder_drive_id=FROZEN_CURRENT_FOLDER_DRIVE_ID,
        parity_staging_folder_drive_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        run_root=root,
        scratch_dir=scratch,
        generation_id=FROZEN_GENERATION_ID,
        data_plane_impl_version=FROZEN_IMPL_VERSION,
    )
    scoped_drive = _SingleSourceDriveApi(api, dict(raw_item))
    run_delta(config, scoped_drive)
    built = _validate_local_candidate(root, raw_item)
    if built is None:
        raise RuntimeError("V31_MARCH_DATA_PLANE_OUTPUT_INVALID")
    data, sem, sem_bytes = built
    return root, data, sem, sem_bytes, raw_access_mode


def _local_packet(
    *,
    root: Path,
    data: Mapping[str, Any],
    row: Mapping[str, Any],
    manifest_index: int,
    bundle_cache: dict[str, tuple[str, ...]],
):
    bundle_name = str(row.get("bundle_name") or "")
    line_number = int(row.get("bundle_line_number") or 0)
    if not bundle_name or line_number <= 0:
        raise RuntimeError(f"V31_MARCH_BAD_SEMANTIC_MANIFEST_ROW:{manifest_index}")
    lines = bundle_cache.get(bundle_name)
    if lines is None:
        path = root / "02_SEMANTIC_BUNDLES" / bundle_name
        if not path.is_file():
            raise RuntimeError(f"V31_MARCH_SEMANTIC_BUNDLE_MISSING:{bundle_name}")
        lines = tuple(path.read_text(encoding="utf-8").splitlines())
        bundle_cache.clear()
        bundle_cache[bundle_name] = lines
    idx = line_number - 1
    if idx < 0 or idx >= len(lines):
        raise RuntimeError(f"V31_MARCH_SEMANTIC_BUNDLE_LINE_RANGE:{bundle_name}:{line_number}")
    obj = json.loads(lines[idx])
    packet = parse_semantic_packet(obj)
    expected = {
        "generation_id": str(data["generation_id"]),
        "source_drive_id": str(data["source_drive_id"]),
        "source_name": str(data["source_name"]),
        "source_sha256": str(data["source_sha256"]),
        "trading_date": str(row["trading_date"]),
        "ticker": str(row["ticker"]),
        "first_clock_time": str(row["first_clock_time"]),
        "last_clock_time": str(row["last_clock_time"]),
        "data_row_count": int(row["data_row_count"]),
        "source_row_first": int(row["source_row_first"]),
        "source_row_last": int(row["source_row_last"]),
    }
    if packet.identity.as_dict() != expected:
        raise RuntimeError(f"V31_MARCH_PACKET_IDENTITY_MISMATCH:{manifest_index}")
    return packet


def _build_march_normalized_cache(
    *,
    root: Path,
    data: Mapping[str, Any],
    sem: list[dict[str, Any]],
    sem_bytes: bytes,
    raw_item: Mapping[str, Any],
    raw_access_mode: str,
) -> dict[str, Any]:
    source = MARCH_2025_SOURCE
    target = v12r._cache_path(source)
    meta_path = v12r._meta_path(source)
    expected_td = len(sem)
    expected_rows = sum(int(x["data_row_count"]) for x in sem)
    if (
        target.is_file()
        and meta_path.is_file()
    ):
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            old = {}
        if (
            old.get("schema") == v12r.CACHE_SCHEMA
            and old.get("source_name") == source
            and old.get("complete") is True
            and str(old.get("source_drive_id") or "") == str(raw_item.get("id") or "")
            and str(old.get("source_sha256") or "") == str(data.get("source_sha256") or "")
            and int(old.get("ticker_days", -1)) == expected_td
            and int(old.get("rows", -1)) == expected_rows
            and int(old.get("cached_ticker_days", -1)) == expected_td
            and int(old.get("cached_session_rows", -1)) == expected_rows
        ):
            return {**old, "v31_cache_action": "REUSED_EXACT_MARCH_NORMALIZED_CACHE"}

    tmp = target.with_suffix(target.suffix + ".tmp")
    bundle_cache: dict[str, tuple[str, ...]] = {}
    ticker_days = 0
    session_rows = 0
    dates: list[str] = []
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        for idx, row in enumerate(sem):
            packet = _local_packet(
                root=root,
                data=data,
                row=row,
                manifest_index=idx,
                bundle_cache=bundle_cache,
            )
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(x) for x in all_bars if x.get("session_eligible")]
            obj = {
                "ticker": str(packet.identity.ticker),
                "date": str(packet.identity.trading_date),
                "bars": bars,
            }
            fh.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
            ticker_days += 1
            session_rows += len(bars)
            dates.append(str(packet.identity.trading_date))
    if ticker_days != expected_td:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"V31_MARCH_CACHE_TICKER_DAY_MISMATCH:{ticker_days}!={expected_td}")
    if session_rows != expected_rows:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"V31_MARCH_CACHE_SESSION_ROW_MISMATCH:{session_rows}!={expected_rows}")
    tmp.replace(target)
    meta = {
        "schema": v12r.CACHE_SCHEMA,
        "source_name": source,
        "source_drive_id": str(data["source_drive_id"]),
        "source_sha256": str(data["source_sha256"]),
        "generation_id": str(data["generation_id"]),
        "semantic_manifest_fingerprint": hashlib.sha256(sem_bytes).hexdigest(),
        "ticker_days": expected_td,
        "rows": expected_rows,
        "cached_ticker_days": ticker_days,
        "cached_session_rows": session_rows,
        "complete": True,
        "v31_march_catchup": True,
        "v31_raw_access_mode": raw_access_mode,
        "v31_current_raw_drive_id": str(raw_item["id"]),
        "v31_current_raw_size": int(raw_item["size"]) if raw_item.get("size") is not None else None,
        "v31_current_raw_md5": raw_item.get("md5Checksum"),
        "first_date": min(dates),
        "last_date": max(dates),
    }
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return {**meta, "v31_cache_action": "BUILT_MARCH_FROM_CURRENT_CANONICAL_RAW_VIA_FROZEN_V2_DATA_PLANE"}


def _march_source(api, raw_item: Mapping[str, Any], *, ensure_cache: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    if not ensure_cache:
        meta_path = v12r._meta_path(MARCH_2025_SOURCE)
        cache_path = v12r._cache_path(MARCH_2025_SOURCE)
        if not meta_path.is_file() or not cache_path.is_file():
            raise RuntimeError("V31_MARCH_CACHE_REQUIRED_FOR_NO_BUILD_MODE")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cache_action = "REUSED_EXISTING_MARCH_CACHE_NO_BUILD_MODE"
    else:
        root, data, sem, sem_bytes, raw_access_mode = _ensure_march_data_plane(api, raw_item)
        meta = _build_march_normalized_cache(
            root=root,
            data=data,
            sem=sem,
            sem_bytes=sem_bytes,
            raw_item=raw_item,
            raw_access_mode=raw_access_mode,
        )
        cache_action = str(meta.get("v31_cache_action"))

    if (
        meta.get("schema") != v12r.CACHE_SCHEMA
        or meta.get("source_name") != MARCH_2025_SOURCE
        or meta.get("complete") is not True
        or str(meta.get("source_drive_id") or "") != str(raw_item.get("id") or "")
        or int(meta.get("ticker_days", -1)) <= 0
        or int(meta.get("rows", -1)) <= 0
        or int(meta.get("cached_ticker_days", -1)) != int(meta.get("ticker_days", -2))
        or int(meta.get("cached_session_rows", -1)) != int(meta.get("rows", -2))
    ):
        raise RuntimeError("V31_MARCH_CACHE_INVALID_AFTER_BUILD")
    first_date = str(meta.get("first_date") or SOURCE_ENVELOPES[MARCH_2025_SOURCE][0])
    last_date = str(meta.get("last_date") or SOURCE_ENVELOPES[MARCH_2025_SOURCE][1])
    source = {
        "source_name": MARCH_2025_SOURCE,
        "first_date": first_date,
        "last_date": last_date,
        "ticker_days": int(meta["ticker_days"]),
        "rows": int(meta["rows"]),
        "source_drive_id": str(meta["source_drive_id"]),
        "source_sha256": meta.get("source_sha256"),
        "generation_id": meta.get("generation_id"),
        "semantic_manifest_fingerprint": meta.get("semantic_manifest_fingerprint"),
        "cache_schema": meta.get("schema"),
        "cache_complete": True,
        "cache_path": str(v12r._cache_path(MARCH_2025_SOURCE)),
        "meta_path": str(v12r._meta_path(MARCH_2025_SOURCE)),
        "legacy_v2_source": False,
        "march_2025_catchup_source": True,
        "current_raw_drive_id": str(raw_item["id"]),
        "current_raw_size": int(raw_item["size"]) if raw_item.get("size") is not None else None,
        "current_raw_md5": raw_item.get("md5Checksum"),
        "source_identity_mode": "CURRENT_CANONICAL_RAW_FROZEN_V2_DATA_PLANE_CATCHUP",
    }
    return source, {
        "source": MARCH_2025_SOURCE,
        "action": cache_action,
        "raw_drive_id": str(raw_item["id"]),
        "ticker_days": int(meta["ticker_days"]),
        "rows": int(meta["rows"]),
    }


def prepare_full_chronological_sources(*, ensure_cache: bool = True) -> dict[str, Any]:
    api = build_drive_api(read_write=False)
    raw_items = _canonical_raw_items(api)

    selected_by_name: dict[str, dict[str, Any]] = {}
    reused: list[str] = []
    for source in LEGACY_SOURCE_NAMES:
        selected_by_name[source] = _legacy_cache_source(source, raw_items[source])
        reused.append(source)

    march, march_action = _march_source(api, raw_items[MARCH_2025_SOURCE], ensure_cache=ensure_cache)
    selected_by_name[MARCH_2025_SOURCE] = march
    selected = [selected_by_name[name] for name in FULL_CHRONOLOGICAL_SOURCE_NAMES]
    chronology = _assert_chronology(selected)

    legacy = [x for x in selected if x["legacy_v2_source"]]
    legacy_ticker_days = sum(int(x["ticker_days"]) for x in legacy)
    legacy_rows = sum(int(x["rows"]) for x in legacy)
    if len(legacy) != EXPECTED_LEGACY_SOURCE_COUNT:
        raise RuntimeError(f"V31_LEGACY_SOURCE_COUNT_MISMATCH:{len(legacy)}")
    if legacy_ticker_days != EXPECTED_LEGACY_TICKER_DAYS or legacy_rows != EXPECTED_LEGACY_MINUTE_ROWS:
        raise RuntimeError(
            f"V31_LEGACY_BASELINE_ACCOUNTING_MISMATCH:{legacy_ticker_days}:{legacy_rows}"
        )

    full_ticker_days = sum(int(x["ticker_days"]) for x in selected)
    full_rows = sum(int(x["rows"]) for x in selected)
    if full_ticker_days <= legacy_ticker_days or full_rows <= legacy_rows:
        raise RuntimeError(
            f"V31_MARCH_DID_NOT_EXPAND_CORPUS:{full_ticker_days}:{full_rows}:"
            f"{legacy_ticker_days}:{legacy_rows}"
        )

    digest_payload = [
        {
            "source_name": x["source_name"],
            "first_date": x["first_date"],
            "last_date": x["last_date"],
            "ticker_days": int(x["ticker_days"]),
            "rows": int(x["rows"]),
            "source_drive_id": x.get("source_drive_id"),
            "source_sha256": x.get("source_sha256"),
            "generation_id": x.get("generation_id"),
            "semantic_manifest_fingerprint": x.get("semantic_manifest_fingerprint"),
        }
        for x in selected
    ]
    corpus_digest = _sha(digest_payload)

    return {
        "schema": "A1_V31_FULL_CHRONOLOGICAL_SOURCE_CATALOG_V2",
        "status": "PASS",
        "sources": selected,
        "source_names": list(FULL_CHRONOLOGICAL_SOURCE_NAMES),
        "source_count": len(selected),
        "legacy_source_count": len(legacy),
        "legacy_ticker_days": legacy_ticker_days,
        "legacy_minute_rows": legacy_rows,
        "march_source": MARCH_2025_SOURCE,
        "march_ticker_days": int(march["ticker_days"]),
        "march_minute_rows": int(march["rows"]),
        "full_ticker_days": full_ticker_days,
        "full_minute_rows": full_rows,
        "chronology": chronology,
        "cache_status": {
            "reused_legacy_sources": reused,
            "march": march_action,
            "cache_root": str(v12r._cache_root()),
            "legacy_data_plane_not_rerun": True,
            "march_data_plane_built_from_current_raw_only_if_needed": True,
        },
        "current_raw_folder_drive_id": FROZEN_RAW_FOLDER_DRIVE_ID,
        "corpus_digest_sha256": corpus_digest,
    }


def main() -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--ensure-cache", action="store_true")
    a = p.parse_args()
    result = prepare_full_chronological_sources(ensure_cache=bool(a.ensure_cache))
    Path(a.output).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "schema": result["schema"],
                "status": result["status"],
                "source_count": result["source_count"],
                "legacy_ticker_days": result["legacy_ticker_days"],
                "march_ticker_days": result["march_ticker_days"],
                "march_minute_rows": result["march_minute_rows"],
                "full_ticker_days": result["full_ticker_days"],
                "full_minute_rows": result["full_minute_rows"],
                "corpus_digest_sha256": result["corpus_digest_sha256"],
                "march_cache_action": result["cache_status"]["march"]["action"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
