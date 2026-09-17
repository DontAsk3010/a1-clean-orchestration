from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict

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


def _sha(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    if not (str(feb["last_date"]) < str(march["first_date"]) <= str(march["last_date"]) < str(april["first_date"])):
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


def prepare_full_chronological_sources(*, ensure_cache: bool = True) -> dict[str, Any]:
    discovered = {str(x["source_name"]): dict(x) for x in _discover_sources_strict()}
    missing = [name for name in FULL_CHRONOLOGICAL_SOURCE_NAMES if name not in discovered]
    if missing:
        raise RuntimeError(f"V31_REQUIRED_SOURCE_MISSING:{missing}")

    selected = [dict(discovered[name]) for name in FULL_CHRONOLOGICAL_SOURCE_NAMES]
    chronology = _assert_chronology(selected)

    if ensure_cache:
        cache_status = v12r._ensure_cache(selected)
    else:
        cache_status = {"reused_sources": [], "built_sources": [], "cache_root": str(v12r._cache_root())}

    enriched: list[dict[str, Any]] = []
    invalid: list[str] = []
    for src in selected:
        source = str(src["source_name"])
        meta_path = v12r._meta_path(source)
        cache_path = v12r._cache_path(source)
        if not meta_path.is_file() or not cache_path.is_file():
            invalid.append(f"{source}:CACHE_OR_META_MISSING")
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            invalid.append(f"{source}:META_UNREADABLE")
            continue
        ok = (
            meta.get("schema") == v12r.CACHE_SCHEMA
            and meta.get("complete") is True
            and meta.get("source_name") == source
            and int(meta.get("ticker_days", -1)) == int(src["ticker_days"])
            and int(meta.get("rows", -1)) == int(src["rows"])
            and int(meta.get("cached_ticker_days", -2)) == int(src["ticker_days"])
        )
        if not ok:
            invalid.append(f"{source}:CACHE_ACCOUNTING_OR_IDENTITY_MISMATCH")
            continue
        enriched.append(
            {
                **src,
                "source_drive_id": meta.get("source_drive_id"),
                "source_sha256": meta.get("source_sha256"),
                "generation_id": meta.get("generation_id"),
                "semantic_manifest_fingerprint": meta.get("semantic_manifest_fingerprint"),
                "cache_schema": meta.get("schema"),
                "cache_complete": True,
                "cache_path": str(cache_path),
                "meta_path": str(meta_path),
                "legacy_v2_source": source in LEGACY_SOURCE_NAMES,
                "march_2025_catchup_source": source == MARCH_2025_SOURCE,
            }
        )

    if invalid or len(enriched) != EXPECTED_FULL_SOURCE_COUNT:
        raise RuntimeError(f"V31_CACHE_CATALOG_NOT_READY:{json.dumps({'invalid': invalid}, sort_keys=True)}")

    legacy = [x for x in enriched if x["legacy_v2_source"]]
    march = next(x for x in enriched if x["march_2025_catchup_source"])
    legacy_ticker_days = sum(int(x["ticker_days"]) for x in legacy)
    legacy_rows = sum(int(x["rows"]) for x in legacy)
    if len(legacy) != EXPECTED_LEGACY_SOURCE_COUNT:
        raise RuntimeError(f"V31_LEGACY_SOURCE_COUNT_MISMATCH:{len(legacy)}")
    if legacy_ticker_days != EXPECTED_LEGACY_TICKER_DAYS or legacy_rows != EXPECTED_LEGACY_MINUTE_ROWS:
        raise RuntimeError(
            f"V31_LEGACY_BASELINE_ACCOUNTING_MISMATCH:{legacy_ticker_days}:{legacy_rows}"
        )

    full_ticker_days = sum(int(x["ticker_days"]) for x in enriched)
    full_rows = sum(int(x["rows"]) for x in enriched)
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
        for x in enriched
    ]
    corpus_digest = _sha(digest_payload)

    return {
        "schema": "A1_V31_FULL_CHRONOLOGICAL_SOURCE_CATALOG_V1",
        "status": "PASS",
        "sources": enriched,
        "source_names": list(FULL_CHRONOLOGICAL_SOURCE_NAMES),
        "source_count": len(enriched),
        "legacy_source_count": len(legacy),
        "legacy_ticker_days": legacy_ticker_days,
        "legacy_minute_rows": legacy_rows,
        "march_source": MARCH_2025_SOURCE,
        "march_ticker_days": int(march["ticker_days"]),
        "march_minute_rows": int(march["rows"]),
        "full_ticker_days": full_ticker_days,
        "full_minute_rows": full_rows,
        "chronology": chronology,
        "cache_status": cache_status,
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
                "full_ticker_days": result["full_ticker_days"],
                "full_minute_rows": result["full_minute_rows"],
                "corpus_digest_sha256": result["corpus_digest_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
