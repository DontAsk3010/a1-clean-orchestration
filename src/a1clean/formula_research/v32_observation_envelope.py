from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

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
from ..source_parity import _SingleSourceDriveApi
from . import telegram_mg_structure_v12_runner as v12r
from .formula_replay import packet_to_formula_bars
from .haka_haki_reconstruction import DEC_2024_CONTRACT, reconstruct_bar
from .full_chronological_cache_catalog import (
    FULL_CHRONOLOGICAL_SOURCE_NAMES,
    _canonical_raw_items,
    _download_raw_to_stage,
    _hash_file,
    prepare_full_chronological_sources,
)

CACHE_SCHEMA = "A1_V32_FULL_OBSERVATION_ENVELOPE_CACHE_V3"

PHASE_FIELDS = (
    "IDX_CLOCK_RULESET_CODE",
    "IDX_REGULAR_CLOCK_SESSION_CODE",
    "CLK_PREOPEN_INPUT_FLAG",
    "CLK_PREOPEN_MATCH_FLAG",
    "CLK_REGULAR_SESSION1_FLAG",
    "CLK_OFFICIAL_MIDDAY_BREAK_FLAG",
    "CLK_REGULAR_SESSION2_FLAG",
    "CLK_PRECLOSE_INPUT_FLAG",
    "CLK_PRECLOSE_MATCH_FLAG",
    "CLK_POSTCLOSE_FLAG",
    "CLK_PREOPEN_NCP_NO_WITHDRAW_FLAG",
    "CLK_PREOPEN_NCP_NO_AMEND_FLAG",
    "CLK_PRECLOSE_NCP_NO_WITHDRAW_FLAG",
    "CLK_PRECLOSE_NCP_NO_AMEND_FLAG",
    "CLK_RANDOM_CLOSING_FLAG",
    "CLK_WATCHLIST_IEP_WINDOW_FLAG",
)


def _slug(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _root() -> Path:
    root = Path.home() / ".a1clean" / "v32_full_observation_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_path(source: str) -> Path:
    return _root() / f"{_slug(source)}.jsonl.gz"


def _meta_path(source: str) -> Path:
    return _root() / f"{_slug(source)}.meta.json"


def _flag_value(row: Mapping[str, str], field: str) -> bool:
    raw = row.get(field)
    if raw is None or str(raw).strip() == "":
        return False
    try:
        return float(raw) != 0.0
    except ValueError:
        return str(raw).strip().upper() in {"TRUE", "T", "YES", "Y"}


def _num_value(row: Mapping[str, str], field: str) -> float | None:
    raw = row.get(field)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _text_value(row: Mapping[str, str], field: str) -> str | None:
    raw = row.get(field)
    if raw is None or str(raw).strip() == "":
        return None
    return str(raw).strip()


def classify_phase(row: Mapping[str, str]) -> str:
    # Evidence hierarchy uses source flags, never clock inference.
    if _flag_value(row, "CLK_PREOPEN_MATCH_FLAG"):
        return "PREOPEN_MATCH"
    if _flag_value(row, "CLK_PREOPEN_INPUT_FLAG"):
        return "PREOPEN_INPUT"
    if _flag_value(row, "CLK_REGULAR_SESSION1_FLAG"):
        return "REGULAR_SESSION1"
    if _flag_value(row, "CLK_OFFICIAL_MIDDAY_BREAK_FLAG"):
        return "OFFICIAL_MIDDAY_BREAK"
    if _flag_value(row, "CLK_REGULAR_SESSION2_FLAG"):
        return "REGULAR_SESSION2"
    if _flag_value(row, "CLK_PRECLOSE_MATCH_FLAG"):
        return "PRECLOSE_MATCH"
    if _flag_value(row, "CLK_PRECLOSE_INPUT_FLAG"):
        return "PRECLOSE_INPUT"
    if _flag_value(row, "CLK_POSTCLOSE_FLAG"):
        return "POSTCLOSE"
    return "OTHER_SOURCE_SUPPORTED_PHASE"


def packet_to_envelope_bars(packet, *, allow_haka_haki: bool = False) -> list[dict[str, Any]]:
    all_formula_bars, _ = packet_to_formula_bars(packet)
    missing = [field for field in PHASE_FIELDS if field not in packet.header]
    if missing:
        raise RuntimeError(f"V32_PHASE_FIELD_MISSING:{missing}")
    if len(all_formula_bars) != len(packet.rows):
        raise RuntimeError("V32_PACKET_FORMULA_LENGTH_MISMATCH")

    out: list[dict[str, Any]] = []
    packet_source_rows = tuple(getattr(packet, "source_rows", ()) or ())
    source_row_first = int(packet.identity.source_row_first)
    if packet_source_rows and len(packet_source_rows) != len(packet.rows):
        raise RuntimeError("V32_PACKET_SOURCE_ROW_CARDINALITY_MISMATCH")
    for i, (raw, base) in enumerate(zip(packet.rows, all_formula_bars, strict=True)):
        phase = classify_phase(raw)
        flags = {
            field: _flag_value(raw, field)
            for field in PHASE_FIELDS
            if field not in {"IDX_CLOCK_RULESET_CODE", "IDX_REGULAR_CLOCK_SESSION_CODE"}
        }
        clock_ruleset_code = _text_value(raw, "IDX_CLOCK_RULESET_CODE")
        session_code_num = _num_value(raw, "IDX_REGULAR_CLOCK_SESSION_CODE")
        session_code = int(session_code_num) if session_code_num is not None and session_code_num.is_integer() else session_code_num
        # Keep two authorities separate:
        # 1) source-proven clock phase, and
        # 2) legacy formula/behavior eligibility (ordinary continuously quoted stock).
        # They are not required to be identical. A row can be source-proven regular
        # phase while remaining outside the legacy behavior stream because the symbol
        # is not an ordinary continuously quoted stock. Such a row must stay in the
        # full observation envelope rather than being rejected or silently discarded.
        source_regular_phase = phase in {"REGULAR_SESSION1", "REGULAR_SESSION2"}
        regular = bool(base.get("session_eligible"))
        if source_regular_phase and regular:
            phase_behavior_relation = "SOURCE_REGULAR_AND_BEHAVIOR_ELIGIBLE"
            behavior_exclusion_reason = None
        elif source_regular_phase and not regular:
            phase_behavior_relation = "SOURCE_REGULAR_BUT_BEHAVIOR_INELIGIBLE"
            behavior_exclusion_reason = "LEGACY_FORMULA_SYMBOL_OR_SESSION_ELIGIBILITY_FALSE"
        elif (not source_regular_phase) and regular:
            phase_behavior_relation = "SOURCE_NONREGULAR_BUT_LEGACY_BEHAVIOR_ELIGIBLE"
            behavior_exclusion_reason = None
        else:
            phase_behavior_relation = "SOURCE_NONREGULAR_AND_BEHAVIOR_INELIGIBLE"
            behavior_exclusion_reason = "SOURCE_NONREGULAR_PHASE"
        if allow_haka_haki:
            hh = reconstruct_bar(base)
            haka = hh.get("haka")
            haki = hh.get("haki")
            haka_haki_status = str(hh.get("status") or "UNKNOWN")
        else:
            haka = None
            haki = None
            haka_haki_status = "SEMANTICS_UNPROVEN_FOR_SOURCE"
        out.append(
            {
                **dict(base),
                "source_row": int(packet_source_rows[i]) if packet_source_rows else source_row_first + i,
                "source_phase": phase,
                "observation_role": phase,
                "source_regular_phase": source_regular_phase,
                "legacy_formula_session_eligible": regular,
                "phase_behavior_eligibility_relation": phase_behavior_relation,
                "behavior_exclusion_reason": behavior_exclusion_reason,
                "regular_behavior_eligible": regular,
                "nonregular_context_observation": not regular,
                "idx_clock_ruleset_code": clock_ruleset_code,
                "idx_regular_clock_session_code": session_code,
                "phase_flags": flags,
                "haka": haka,
                "haki": haki,
                "haka_haki_status": haka_haki_status,
                # Preserve every physically present source field value, including
                # fields not currently understood or consumed by Formula Research.
                # Values are aligned to packet-level source_header in exact header order.
                "source_field_values": [raw.get(field) for field in packet.header],
                "source_field_count": len(packet.header),
                "source_packet_fingerprint": getattr(packet, "packet_fingerprint", None),
            }
        )
    return out


def _exact_local_raw(api, item: Mapping[str, Any], source: str) -> Path:
    expected_size = int(item.get("size") or -1)
    expected_md5 = str(item.get("md5Checksum") or "").lower()
    configured = os.environ.get("A1_RAW_DIR")
    if configured:
        candidate = Path(configured).expanduser().resolve() / source
        if candidate.is_file() and candidate.stat().st_size == expected_size and expected_md5:
            actual_md5, _ = _hash_file(candidate)
            if actual_md5.lower() == expected_md5:
                return candidate
    staged, _ = _download_raw_to_stage(api, item, source)
    return staged


def _data_plane_root(source: str, item: Mapping[str, Any]) -> Path:
    key = hashlib.sha256(
        (source + "|" + str(item.get("id")) + "|" + str(item.get("md5Checksum")) + "|" + str(item.get("size"))).encode("utf-8")
    ).hexdigest()[:24]
    return Path.home() / ".a1clean" / "v32_full_data_plane" / key


def _data_plane_valid(root: Path, source: str, item: Mapping[str, Any]) -> bool:
    stem = Path(source).stem
    data_path = root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json"
    sem_path = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    if not data_path.is_file() or not sem_path.is_file():
        return False
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
        sem = json.loads(sem_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        data.get("status") == "ACCESS_READY_FOR_AI"
        and data.get("source_name") == source
        and str(data.get("source_drive_id") or "") == str(item.get("id") or "")
        and isinstance(sem, list)
        and len(sem) == int(data.get("ticker_day_objects") or -1)
        and sum(int(x.get("data_row_count") or 0) for x in sem) == int(data.get("source_data_rows") or -1)
    )


def _ensure_data_plane(api, source: str, item: Mapping[str, Any]) -> Path:
    root = _data_plane_root(source, item)
    if _data_plane_valid(root, source, item):
        return root
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    raw = _exact_local_raw(api, item, source)
    scratch = root / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    config = DataPlaneConfig(
        engine_root=root,
        raw_dir=raw.parent,
        runtime_ingest_dir=root,
        raw_folder_drive_id=FROZEN_RAW_FOLDER_DRIVE_ID,
        current_folder_drive_id=FROZEN_CURRENT_FOLDER_DRIVE_ID,
        parity_staging_folder_drive_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        run_root=root,
        scratch_dir=scratch,
        generation_id=FROZEN_GENERATION_ID,
        data_plane_impl_version=FROZEN_IMPL_VERSION,
    )
    run_delta(config, _SingleSourceDriveApi(api, dict(item)))
    if not _data_plane_valid(root, source, item):
        raise RuntimeError(f"V32_DATA_PLANE_INVALID_AFTER_BUILD:{source}")
    return root


def _cache_valid(source: str, expected: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    path = _cache_path(source)
    meta_path = _meta_path(source)
    if not path.is_file() or not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        meta.get("schema") == CACHE_SCHEMA
        and meta.get("complete") is True
        and meta.get("source_name") == source
        and str(meta.get("source_drive_id") or "") == str(item.get("id") or "")
        and int(meta.get("ticker_days", -1)) == int(expected.get("ticker_days", -2))
        and int(meta.get("regular_rows", -1)) == int(expected.get("rows", -2))
        and int(meta.get("source_rows", -1)) == int(expected.get("source_rows", -2))
    )


def _load_packet_from_local(root: Path, manifest_row: Mapping[str, Any], cache: dict[str, tuple[str, ...]]):
    bundle_name = str(manifest_row.get("bundle_name") or "")
    line_number = int(manifest_row.get("bundle_line_number") or 0)
    if not bundle_name or line_number <= 0:
        raise RuntimeError("V32_BAD_SEMANTIC_MANIFEST_ROW")
    lines = cache.get(bundle_name)
    if lines is None:
        path = root / "02_SEMANTIC_BUNDLES" / bundle_name
        if not path.is_file():
            raise RuntimeError(f"V32_SEMANTIC_BUNDLE_MISSING:{bundle_name}")
        lines = tuple(path.read_text(encoding="utf-8").splitlines())
        cache.clear()
        cache[bundle_name] = lines
    idx = line_number - 1
    if idx < 0 or idx >= len(lines):
        raise RuntimeError(f"V32_SEMANTIC_BUNDLE_LINE_RANGE:{bundle_name}:{line_number}")
    return parse_semantic_packet(json.loads(lines[idx]))


def build_source_cache(
    api,
    *,
    source: str,
    expected: Mapping[str, Any],
    item: Mapping[str, Any],
) -> dict[str, Any]:
    if _cache_valid(source, expected, item):
        meta = json.loads(_meta_path(source).read_text(encoding="utf-8"))
        return {**meta, "cache_action": "REUSED_EXACT_V32_ENVELOPE_CACHE"}

    root = _ensure_data_plane(api, source, item)
    stem = Path(source).stem
    data_path = root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json"
    sem_path = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    sem = json.loads(sem_path.read_text(encoding="utf-8"))

    target = _cache_path(source)
    tmp = target.with_suffix(target.suffix + ".tmp")
    packet_count = 0
    source_rows = 0
    regular_rows = 0
    nonregular_rows = 0
    phase_counts = Counter()
    bundle_cache: dict[str, tuple[str, ...]] = {}
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        for row in sem:
            packet = _load_packet_from_local(root, row, bundle_cache)
            bars = packet_to_envelope_bars(
                packet,
                allow_haka_haki=source == str(DEC_2024_CONTRACT["source_name"]),
            )
            regular = sum(1 for x in bars if x["regular_behavior_eligible"])
            source_rows += len(bars)
            regular_rows += regular
            nonregular_rows += len(bars) - regular
            phase_counts.update(str(x["source_phase"]) for x in bars)
            fh.write(
                json.dumps(
                    {
                        "ticker": str(packet.identity.ticker),
                        "date": str(packet.identity.trading_date),
                        "source_header": list(packet.header),
                        "source_header_field_count": len(packet.header),
                        "source_packet_fingerprint": getattr(packet, "packet_fingerprint", None),
                        "all_source_columns_retained": True,
                        "bars": bars,
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            packet_count += 1

    if packet_count != int(expected["ticker_days"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"V32_TICKER_DAY_RECONCILIATION_FAIL:{source}:{packet_count}:{expected['ticker_days']}")
    if source_rows != int(expected["source_rows"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"V32_SOURCE_ROW_RECONCILIATION_FAIL:{source}:{source_rows}:{expected['source_rows']}")
    if regular_rows != int(expected["rows"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"V32_REGULAR_ROW_RECONCILIATION_FAIL:{source}:{regular_rows}:{expected['rows']}")
    if source_rows != int(data["source_data_rows"]):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"V32_DATA_PLANE_SOURCE_ROW_RECONCILIATION_FAIL:{source}")
    tmp.replace(target)

    meta = {
        "schema": CACHE_SCHEMA,
        "complete": True,
        "source_name": source,
        "source_drive_id": str(data["source_drive_id"]),
        "source_sha256": str(data["source_sha256"]),
        "generation_id": str(data["generation_id"]),
        "ticker_days": packet_count,
        "source_rows": source_rows,
        "regular_rows": regular_rows,
        "nonregular_rows": nonregular_rows,
        "phase_counts": dict(sorted(phase_counts.items())),
        "cache_path": str(target),
        "all_source_columns_retained": True,
        "source_values_retained_for_every_row": True,
        "source_packet_fingerprint_preserved": True,
        "canonical_raw_untouched": True,
        "v31_untouched": True,
    }
    _meta_path(source).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")

    # The compact full-envelope cache is the durable V3.2 input. Heavy temporary
    # data-plane output can be rebuilt deterministically from the exact RAW if needed.
    shutil.rmtree(root, ignore_errors=True)
    return {**meta, "cache_action": "BUILT_FROM_CURRENT_CANONICAL_RAW_VIA_FROZEN_V2_DATA_PLANE"}


def ensure_full_observation_caches() -> dict[str, Any]:
    v31 = prepare_full_chronological_sources(ensure_cache=True)
    expected_by_name = {str(x["source_name"]): x for x in v31["sources"]}
    api = build_drive_api(read_write=False)
    raw_items = _canonical_raw_items(api)

    summaries: list[dict[str, Any]] = []
    totals = Counter()
    for source in FULL_CHRONOLOGICAL_SOURCE_NAMES:
        summary = build_source_cache(
            api,
            source=source,
            expected=expected_by_name[source],
            item=raw_items[source],
        )
        summaries.append(summary)
        totals["ticker_days"] += int(summary["ticker_days"])
        totals["source_rows"] += int(summary["source_rows"])
        totals["regular_rows"] += int(summary["regular_rows"])
        totals["nonregular_rows"] += int(summary["nonregular_rows"])

    if totals["ticker_days"] != int(v31["full_ticker_days"]):
        raise RuntimeError(f"V32_GLOBAL_TICKER_DAY_MISMATCH:{dict(totals)}")
    if totals["regular_rows"] != int(v31["full_minute_rows"]):
        raise RuntimeError(f"V32_GLOBAL_REGULAR_ROW_MISMATCH:{dict(totals)}")
    expected_source_rows = sum(int(x["source_rows"]) for x in v31["sources"])
    if totals["source_rows"] != expected_source_rows:
        raise RuntimeError(f"V32_GLOBAL_SOURCE_ROW_MISMATCH:{dict(totals)}:{expected_source_rows}")

    digest_payload = [
        {
            "source_name": x["source_name"],
            "source_drive_id": x["source_drive_id"],
            "source_sha256": x["source_sha256"],
            "ticker_days": x["ticker_days"],
            "source_rows": x["source_rows"],
            "regular_rows": x["regular_rows"],
            "nonregular_rows": x["nonregular_rows"],
            "phase_counts": x["phase_counts"],
        }
        for x in summaries
    ]
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "A1_V32_FULL_OBSERVATION_ENVELOPE_CATALOG_V1",
        "status": "PASS",
        "v31_corpus_digest_sha256": v31["corpus_digest_sha256"],
        "envelope_digest_sha256": digest,
        "source_count": len(summaries),
        "ticker_days": int(totals["ticker_days"]),
        "source_rows": int(totals["source_rows"]),
        "regular_rows": int(totals["regular_rows"]),
        "nonregular_rows": int(totals["nonregular_rows"]),
        "sources": summaries,
    }


def iter_envelope_cached(source: str):
    path = _cache_path(source)
    if not path.is_file():
        raise RuntimeError(f"V32_ENVELOPE_CACHE_MISSING:{source}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                packet = json.loads(line)
                header = packet.get("source_header")
                bars = packet.get("bars")
                if packet.get("all_source_columns_retained") is not True:
                    raise RuntimeError(f"V32_PACKET_SOURCE_COLUMNS_NOT_RETAINED:{source}")
                if not isinstance(header, list) or not header:
                    raise RuntimeError(f"V32_PACKET_SOURCE_HEADER_MISSING:{source}")
                if not isinstance(bars, list):
                    raise RuntimeError(f"V32_PACKET_BARS_NOT_LIST:{source}")
                for i, bar in enumerate(bars):
                    values = bar.get("source_field_values")
                    if not isinstance(values, list) or len(values) != len(header):
                        raise RuntimeError(
                            f"V32_PACKET_SOURCE_VALUES_MISMATCH:{source}:{i}:{len(header)}"
                        )
                    if int(bar.get("source_field_count", -1)) != len(header):
                        raise RuntimeError(
                            f"V32_PACKET_SOURCE_FIELD_COUNT_MISMATCH:{source}:{i}"
                        )
                yield packet
