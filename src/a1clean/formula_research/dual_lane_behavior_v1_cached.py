from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import dual_lane_behavior_v1 as core
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r


def _governed_sources_from_durable_cache() -> list[dict[str, Any]]:
    names = list(v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B)
    if v11.RESERVED_OOS in names:
        raise AssertionError("RESERVED_OOS_MUST_NOT_ENTER_DUAL_LANE_CACHE_CATALOG")

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
            "DUAL_LANE_DURABLE_CACHE_CATALOG_NOT_READY:"
            + json.dumps({"missing": missing, "invalid": invalid}, sort_keys=True)
        )
    if [str(x["source_name"]) for x in sources] != names:
        raise AssertionError("DUAL_LANE_CACHE_SOURCE_ORDER_MISMATCH")
    return sources


def build_report(*, prior_days: int, buy_fee: float, sell_fee: float, min_support: int) -> dict[str, Any]:
    sources = _governed_sources_from_durable_cache()
    original = v11._ordered_governed_sources
    v11._ordered_governed_sources = lambda: [dict(x) for x in sources]
    try:
        report = core.build_report(
            prior_days=prior_days,
            buy_fee=buy_fee,
            sell_fee=sell_fee,
            min_support=min_support,
        )
    finally:
        v11._ordered_governed_sources = original

    report["source_catalog"] = "DURABLE_CACHE_META_ONLY_NO_DRIVE_MANIFEST_DISCOVERY"
    report["cache_source_count"] = len(sources)
    report["cache_sources"] = [
        {
            "source_name": x["source_name"],
            "ticker_days": x["ticker_days"],
            "rows": x["rows"],
            "source_sha256": x.get("source_sha256"),
            "generation_id": x.get("generation_id"),
            "semantic_manifest_fingerprint": x.get("semantic_manifest_fingerprint"),
        }
        for x in sources
    ]
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "cache_source_count": report["cache_source_count"],
        "strict_survivor_count": report["strict_survivor_count"],
        "counters": report["counters"],
        "ranked": [
            {
                "id": x["id"],
                "pass": x["strict_cross_period_pass"],
                "worst_q25": x["worst_block_q25_net_mfe_pct"],
                "worst_median": x["worst_block_median_net_mfe_pct"],
            }
            for x in report["ranked_formulas"]
        ],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
