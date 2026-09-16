from __future__ import annotations

import json
from typing import Any

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r


def governed_sources_from_durable_cache() -> list[dict[str, Any]]:
    names = list(v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B)
    if v11.RESERVED_OOS in names:
        raise AssertionError("RESERVED_OOS_MUST_NOT_ENTER_CACHE_CATALOG")

    sources: list[dict[str, Any]] = []
    missing: list[str] = []
    invalid: list[str] = []

    for source in names:
        meta_path = v12r._meta_path(source)
        cache_path = v12r._cache_path(source)
        if not meta_path.is_file() or not cache_path.is_file():
            missing.append(source)
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            invalid.append(f"{source}:META_UNREADABLE")
            continue

        ticker_days = int(meta.get("ticker_days", -1))
        rows = int(meta.get("rows", -1))
        cached_ticker_days = int(meta.get("cached_ticker_days", -2))
        complete = meta.get("complete") is True
        schema_ok = meta.get("schema") == v12r.CACHE_SCHEMA
        source_ok = meta.get("source_name") == source
        accounting_ok = ticker_days >= 0 and rows >= 0 and cached_ticker_days == ticker_days

        if not (complete and schema_ok and source_ok and accounting_ok):
            invalid.append(
                f"{source}:schema={meta.get('schema')}:complete={meta.get('complete')}:"
                f"ticker_days={ticker_days}:cached={cached_ticker_days}:rows={rows}"
            )
            continue

        sources.append({
            "source_name": source,
            "ticker_days": ticker_days,
            "rows": rows,
            "source_drive_id": meta.get("source_drive_id"),
            "source_sha256": meta.get("source_sha256"),
            "generation_id": meta.get("generation_id"),
            "semantic_manifest_fingerprint": meta.get("semantic_manifest_fingerprint"),
            "cache_catalog_only": True,
        })

    if missing or invalid:
        raise RuntimeError(
            "DURABLE_CACHE_CATALOG_NOT_READY:"
            + json.dumps({"missing": missing, "invalid": invalid}, sort_keys=True)
        )
    if [str(x["source_name"]) for x in sources] != names:
        raise AssertionError("CACHE_SOURCE_ORDER_MISMATCH")
    return sources
