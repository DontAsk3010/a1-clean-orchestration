from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from .durable_cache_catalog import governed_sources_from_durable_cache
from . import telegram_mg_structure_v12_runner as v12r

SCHEMA = "A1_HAKA_HAKI_SOURCE_BOUND_RECONSTRUCTION_V1"
STATUS = "RESEARCH_EVIDENCE_ONLY_NOT_CANONICAL"

DEC_2024_CONTRACT = {
    "source_name": "Raw Des 02-31-2024.csv",
    "source_drive_id": "1wvBmhpQIV-evJJOPN_g8nks3KZBzmVHC",
    "source_sha256": "5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c",
    "generation_id": "BEHAVIOR_UNIFORM_COLAB_SEMANTIC_GEN_20260910_01",
    "trade_value_semantic": "RAW_Aux2=TRADE_VALUE_1M",
    "nbss_semantic": "RAW_OpenInterest=NBSS_VALUE_1M",
    "availability_rule": "DERIVE_ONLY_WHEN_FLOW_AVAILABLE_AND_MECHANISM_ELIGIBLE_TRUE",
    "zero_rule": "PHYSICAL_ZERO_REMAINS_UNKNOWN_UNLESS_AVAILABILITY_INDEPENDENTLY_PROVEN_TRUE",
}


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _assert_contract(meta: Mapping[str, Any]) -> None:
    for key in ("source_name", "source_drive_id", "source_sha256", "generation_id"):
        expected = str(DEC_2024_CONTRACT[key])
        actual = str(meta.get(key) or "")
        if actual != expected:
            raise AssertionError(f"HAKA_HAKI_SOURCE_CONTRACT_MISMATCH:{key}:{actual}!={expected}")


def reconstruct_bar(bar: Mapping[str, Any]) -> dict[str, Any]:
    trade_value = _f(bar.get("trade_value"))
    nbss = _f(bar.get("nbss"))
    flow_available = bool(bar.get("flow_available", False))
    mechanism_eligible = bool(bar.get("mechanism_eligible", False))

    base = {
        "timestamp": bar.get("timestamp"),
        "trade_value": trade_value,
        "nbss": nbss,
        "flow_available": flow_available,
        "mechanism_eligible": mechanism_eligible,
        "haka": None,
        "haki": None,
        "status": None,
    }

    if trade_value is None or nbss is None:
        base["status"] = "MISSING_INPUT"
        return base
    if nbss == 0.0 and not flow_available:
        base["status"] = "ZERO_AVAILABILITY_UNPROVEN"
        return base
    if not (flow_available and mechanism_eligible):
        base["status"] = "NOT_ELIGIBLE_OR_UNPROVEN"
        return base
    if trade_value < 0:
        base["status"] = "INVALID_NEGATIVE_TRADE_VALUE"
        return base

    haka = (trade_value + nbss) / 2.0
    haki = (trade_value - nbss) / 2.0
    if haka < -1e-9 or haki < -1e-9:
        base["status"] = "INVALID_NEGATIVE_DERIVED_SIDE"
        return base
    if not math.isclose(haka + haki, trade_value, rel_tol=1e-12, abs_tol=1e-6):
        raise AssertionError("HAKA_HAKI_SUM_IDENTITY_FAILED")
    if not math.isclose(haka - haki, nbss, rel_tol=1e-12, abs_tol=1e-6):
        raise AssertionError("HAKA_HAKI_DIFF_IDENTITY_FAILED")

    base["haka"] = haka
    base["haki"] = haki
    base["status"] = "RECONSTRUCTED_PROVEN_SCOPE"
    return base


def build_report() -> dict[str, Any]:
    sources = governed_sources_from_durable_cache()
    meta = next((x for x in sources if x.get("source_name") == DEC_2024_CONTRACT["source_name"]), None)
    if meta is None:
        raise RuntimeError("DEC_2024_DURABLE_CACHE_SOURCE_NOT_FOUND")
    _assert_contract(meta)

    status_counts: Counter[str] = Counter()
    date_counts: dict[str, Counter[str]] = defaultdict(Counter)
    ticker_day_rows: dict[str, dict[str, Any]] = {}
    examples: list[dict[str, Any]] = []
    reconstructed_haka = 0.0
    reconstructed_haki = 0.0
    reconstructed_trade_value = 0.0
    reconstructed_nbss = 0.0
    ticker_days = 0
    rows = 0

    for packet in v12r._iter_cached(DEC_2024_CONTRACT["source_name"]):
        ticker_days += 1
        ticker = str(packet.get("ticker"))
        date = str(packet.get("date"))
        key = f"{date}|{ticker}"
        td = {"date": date, "ticker": ticker, "rows": 0, "reconstructed_rows": 0, "zero_unknown_rows": 0, "invalid_rows": 0}
        for bar in packet.get("bars", []):
            rows += 1
            td["rows"] += 1
            rec = reconstruct_bar(bar)
            status = str(rec["status"])
            status_counts[status] += 1
            date_counts[date][status] += 1
            if status == "RECONSTRUCTED_PROVEN_SCOPE":
                td["reconstructed_rows"] += 1
                reconstructed_haka += float(rec["haka"])
                reconstructed_haki += float(rec["haki"])
                reconstructed_trade_value += float(rec["trade_value"])
                reconstructed_nbss += float(rec["nbss"])
                if len(examples) < 40:
                    examples.append({"date": date, "ticker": ticker, **rec})
            elif status == "ZERO_AVAILABILITY_UNPROVEN":
                td["zero_unknown_rows"] += 1
            elif status.startswith("INVALID_"):
                td["invalid_rows"] += 1
        ticker_day_rows[key] = td

    if not math.isclose(reconstructed_haka + reconstructed_haki, reconstructed_trade_value, rel_tol=1e-12, abs_tol=1e-3):
        raise AssertionError("AGGREGATE_HAKA_HAKI_SUM_IDENTITY_FAILED")
    if not math.isclose(reconstructed_haka - reconstructed_haki, reconstructed_nbss, rel_tol=1e-12, abs_tol=1e-3):
        raise AssertionError("AGGREGATE_HAKA_HAKI_DIFF_IDENTITY_FAILED")

    return {
        "schema": SCHEMA,
        "status": STATUS,
        "source_contract": dict(DEC_2024_CONTRACT),
        "bound_cache_meta": dict(meta),
        "method": "DETERMINISTIC_SOURCE_SCOPED_RECONSTRUCTION_FROM_VALIDATED_TRADE_VALUE_AND_NBSS",
        "equations": {
            "HAKA_VALUE_1M": "(TRADE_VALUE_1M + NBSS_VALUE_1M) / 2",
            "HAKI_VALUE_1M": "(TRADE_VALUE_1M - NBSS_VALUE_1M) / 2",
        },
        "ticker_days": ticker_days,
        "session_rows": rows,
        "status_counts": dict(status_counts),
        "date_status_counts": {k: dict(v) for k, v in sorted(date_counts.items())},
        "aggregate_identity": {
            "reconstructed_trade_value": reconstructed_trade_value,
            "reconstructed_nbss": reconstructed_nbss,
            "reconstructed_haka": reconstructed_haka,
            "reconstructed_haki": reconstructed_haki,
            "haka_plus_haki_equals_trade_value": True,
            "haka_minus_haki_equals_nbss": True,
        },
        "ticker_day_accounting": list(ticker_day_rows.values()),
        "examples": examples,
        "important_semantics": {
            "reconstruction_is_deterministic_semantic_decomposition_not_new_raw_information": True,
            "physical_zero_not_assumed_neutral": True,
            "missing_not_zero": True,
            "raw_inputs_preserved_in_cache": True,
            "reserved_oos_touched": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_report()
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "ticker_days": report["ticker_days"],
        "session_rows": report["session_rows"],
        "status_counts": report["status_counts"],
        "aggregate_identity": report["aggregate_identity"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
