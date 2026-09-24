from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from ..google_drive import build_drive_api
from ..source_preflight import list_canonical_drive_sources
from . import v32_observation_envelope as legacy
from .haka_haki_reconstruction import DEC_2024_CONTRACT
from .source_universe_manifest import (
    assert_historical_baseline_order,
    manifest_digest_is_valid,
    source_names_from_manifest,
)

CATALOG_SCHEMA = "A1_V32_DYNAMIC_FULL_OBSERVATION_ENVELOPE_CATALOG_V1"


def load_source_universe(path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not manifest_digest_is_valid(manifest):
        raise RuntimeError("V32_DYNAMIC_SOURCE_UNIVERSE_MANIFEST_DIGEST_FAIL")
    names = source_names_from_manifest(manifest, require_pass=True)
    assert_historical_baseline_order(names)
    if int(manifest.get("source_count", -1)) != len(names):
        raise RuntimeError("V32_DYNAMIC_SOURCE_UNIVERSE_COUNT_DRIFT")
    return manifest, names


def _raw_items_for_manifest(api, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    physical = list_canonical_drive_sources(api, legacy.FROZEN_RAW_FOLDER_DRIVE_ID)
    by_id: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for item in physical:
        by_id.setdefault(str(item.get("id") or ""), []).append(dict(item))
        by_name.setdefault(str(item.get("name") or ""), []).append(dict(item))

    out: dict[str, dict[str, Any]] = {}
    for record in manifest.get("sources", []):
        source_id = str(record.get("source_drive_id") or "")
        source_name = str(record.get("source_name") or "")
        id_matches = by_id.get(source_id, [])
        if len(id_matches) != 1:
            raise RuntimeError(
                f"V32_DYNAMIC_CANONICAL_SOURCE_ID_CARDINALITY:{source_name}:{source_id}:{len(id_matches)}"
            )
        item = id_matches[0]
        if str(item.get("name") or "") != source_name:
            raise RuntimeError(
                f"V32_DYNAMIC_CANONICAL_SOURCE_NAME_DRIFT:{source_id}:{source_name}:{item.get('name')}"
            )
        if len(by_name.get(source_name, [])) != 1:
            raise RuntimeError(f"V32_DYNAMIC_CANONICAL_SOURCE_NAME_DUPLICATE:{source_name}")
        out[source_name] = item
    if len(out) != int(manifest.get("source_count", -1)):
        raise RuntimeError("V32_DYNAMIC_CANONICAL_RAW_COVERAGE_MISMATCH")
    return out


def _capability(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("schema_source_capability")
    if not isinstance(value, Mapping):
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_CAPABILITY_MISSING:{record.get('source_name')}")
    return value


def _cache_valid(record: Mapping[str, Any]) -> bool:
    source = str(record.get("source_name") or "")
    path = legacy._cache_path(source)
    meta_path = legacy._meta_path(source)
    if not path.is_file() or not meta_path.is_file():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    cap = _capability(record)
    return (
        meta.get("schema") == legacy.CACHE_SCHEMA
        and meta.get("complete") is True
        and meta.get("source_name") == source
        and str(meta.get("source_drive_id") or "") == str(record.get("source_drive_id") or "")
        and str(meta.get("source_sha256") or "") == str(record.get("digest_sha256") or "")
        and int(meta.get("ticker_days", -1)) == int(cap.get("ticker_day_objects", -2))
        and int(meta.get("source_rows", -1)) == int(cap.get("source_data_rows", -2))
    )


def build_source_cache_dynamic(
    api,
    *,
    record: Mapping[str, Any],
    item: Mapping[str, Any],
    source_universe_digest: str,
) -> dict[str, Any]:
    source = str(record.get("source_name") or "")
    cap = _capability(record)
    expected_ticker_days = int(cap.get("ticker_day_objects", -1))
    expected_source_rows = int(cap.get("source_data_rows", -1))
    if expected_ticker_days < 0 or expected_source_rows < 0:
        raise RuntimeError(f"V32_DYNAMIC_SOURCE_EXPECTED_COUNTS_MISSING:{source}")

    if _cache_valid(record):
        meta = json.loads(legacy._meta_path(source).read_text(encoding="utf-8"))
        return {
            **meta,
            "cache_action": "REUSED_EXACT_DIGEST_COMPATIBLE_V32_ENVELOPE_CACHE",
            "source_universe_manifest_digest": source_universe_digest,
        }

    root = legacy._ensure_data_plane(api, source, item)
    stem = Path(source).stem
    data_path = root / "00_MANIFESTS" / f"{stem}__DATA_PLANE_MANIFEST.json"
    sem_path = root / "00_MANIFESTS" / f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    sem = json.loads(sem_path.read_text(encoding="utf-8"))
    if str(data.get("source_drive_id") or "") != str(record.get("source_drive_id") or ""):
        raise RuntimeError(f"V32_DYNAMIC_DATA_PLANE_SOURCE_ID_DRIFT:{source}")
    if str(data.get("source_sha256") or "") != str(record.get("digest_sha256") or ""):
        raise RuntimeError(f"V32_DYNAMIC_DATA_PLANE_SOURCE_DIGEST_DRIFT:{source}")
    if int(data.get("ticker_day_objects", -1)) != expected_ticker_days:
        raise RuntimeError(f"V32_DYNAMIC_DATA_PLANE_TICKER_DAY_DRIFT:{source}")
    if int(data.get("source_data_rows", -1)) != expected_source_rows:
        raise RuntimeError(f"V32_DYNAMIC_DATA_PLANE_SOURCE_ROW_DRIFT:{source}")

    target = legacy._cache_path(source)
    tmp = target.with_suffix(target.suffix + ".tmp")
    packet_count = 0
    source_rows = 0
    regular_rows = 0
    nonregular_rows = 0
    phase_counts = Counter()
    bundle_cache: dict[str, tuple[str, ...]] = {}
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        for row in sem:
            packet = legacy._load_packet_from_local(root, row, bundle_cache)
            bars = legacy.packet_to_envelope_bars(
                packet,
                allow_haka_haki=source == str(DEC_2024_CONTRACT["source_name"]),
            )
            regular = sum(1 for bar in bars if bar["regular_behavior_eligible"])
            source_rows += len(bars)
            regular_rows += regular
            nonregular_rows += len(bars) - regular
            phase_counts.update(str(bar["source_phase"]) for bar in bars)
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

    if packet_count != expected_ticker_days:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"V32_DYNAMIC_TICKER_DAY_RECONCILIATION_FAIL:{source}:{packet_count}:{expected_ticker_days}"
        )
    if source_rows != expected_source_rows:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"V32_DYNAMIC_SOURCE_ROW_RECONCILIATION_FAIL:{source}:{source_rows}:{expected_source_rows}"
        )
    tmp.replace(target)

    meta = {
        "schema": legacy.CACHE_SCHEMA,
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
        "dynamic_source_universe": True,
        "source_universe_manifest_digest": source_universe_digest,
    }
    legacy._meta_path(source).write_text(
        json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8"
    )
    shutil.rmtree(root, ignore_errors=True)
    return {**meta, "cache_action": "BUILT_FROM_GOVERNED_DYNAMIC_SOURCE_VIA_FROZEN_V2_DATA_PLANE"}


def ensure_full_observation_caches_dynamic(source_universe_manifest: Path) -> dict[str, Any]:
    manifest, names = load_source_universe(source_universe_manifest)
    by_name = {str(row.get("source_name") or ""): row for row in manifest.get("sources", [])}
    api = build_drive_api(read_write=False)
    raw_items = _raw_items_for_manifest(api, manifest)

    summaries: list[dict[str, Any]] = []
    totals = Counter()
    for source in names:
        summary = build_source_cache_dynamic(
            api,
            record=by_name[source],
            item=raw_items[source],
            source_universe_digest=str(manifest["manifest_digest"]),
        )
        summaries.append(summary)
        totals["ticker_days"] += int(summary["ticker_days"])
        totals["source_rows"] += int(summary["source_rows"])
        totals["regular_rows"] += int(summary["regular_rows"])
        totals["nonregular_rows"] += int(summary["nonregular_rows"])

    if totals["source_rows"] != totals["regular_rows"] + totals["nonregular_rows"]:
        raise RuntimeError(f"V32_DYNAMIC_GLOBAL_LAYER_ACCOUNTING_FAIL:{dict(totals)}")
    digest_payload = [
        {
            "source_name": row["source_name"],
            "source_drive_id": row["source_drive_id"],
            "source_sha256": row["source_sha256"],
            "ticker_days": row["ticker_days"],
            "source_rows": row["source_rows"],
            "regular_rows": row["regular_rows"],
            "nonregular_rows": row["nonregular_rows"],
            "phase_counts": row["phase_counts"],
        }
        for row in summaries
    ]
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": CATALOG_SCHEMA,
        "status": "PASS",
        "dynamic_source_universe": True,
        "source_universe_manifest_digest": manifest["manifest_digest"],
        "source_count": len(summaries),
        "ticker_days": int(totals["ticker_days"]),
        "source_rows": int(totals["source_rows"]),
        "regular_rows": int(totals["regular_rows"]),
        "nonregular_rows": int(totals["nonregular_rows"]),
        "envelope_digest_sha256": digest,
        "sources": summaries,
    }
