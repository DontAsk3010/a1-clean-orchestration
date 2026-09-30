from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .source_universe_manifest import _digest, manifest_digest_is_valid


SCHEMA = "A1_CLEAN_SOURCE_UNIVERSE_SEMANTIC_DATE_RECONCILIATION_V1"


def _load_manifest(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_RECONCILE_JSON_NOT_OBJECT:{path}")
    if obj.get("status") != "PASS" or not manifest_digest_is_valid(obj):
        raise RuntimeError("SOURCE_UNIVERSE_SEMANTIC_RECONCILE_INPUT_NOT_PASS")
    return obj


def _semantic_envelope(reader: GovernedSourceReader) -> dict[str, Any]:
    rows = list(reader.semantic_manifest_rows)
    if not rows:
        raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_MANIFEST_EMPTY:{reader.identity.source_name}")
    dates = [str(row.trading_date) for row in rows]
    if dates != sorted(dates):
        raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_DATE_ORDER_NONMONOTONIC:{reader.identity.source_name}")
    identity = reader.identity.as_dict()
    first = rows[0]
    last = rows[-1]
    return {
        "source_name": str(identity.get("source_name") or reader.identity.source_name),
        "source_drive_id": str(identity.get("source_drive_id") or ""),
        "source_sha256": str(identity.get("source_sha256") or ""),
        "first_date": str(first.trading_date),
        "first_time": str(first.first_clock_time),
        "last_date": str(last.trading_date),
        "last_time": str(last.last_clock_time),
        "ticker_day_object_count": len(rows),
    }


def reconcile_manifest_date_envelopes(
    manifest: Mapping[str, Any],
    semantic_envelopes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    out = json.loads(json.dumps(manifest))
    if out.get("status") != "PASS" or not manifest_digest_is_valid(out):
        raise RuntimeError("SOURCE_UNIVERSE_SEMANTIC_RECONCILE_INPUT_NOT_PASS")

    mismatches: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for raw_record in out.get("sources", []):
        record = dict(raw_record)
        source_name = str(record.get("source_name") or "")
        envelope = dict(semantic_envelopes.get(source_name) or {})
        if not envelope:
            raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_ENVELOPE_MISSING:{source_name}")
        if str(record.get("source_drive_id") or "") != str(envelope.get("source_drive_id") or ""):
            raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_SOURCE_ID_DRIFT:{source_name}")
        if str(record.get("digest_sha256") or "") != str(envelope.get("source_sha256") or ""):
            raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_SOURCE_DIGEST_DRIFT:{source_name}")

        original = {
            "first_date": record.get("first_date"),
            "first_time": record.get("first_time"),
            "last_date": record.get("last_date"),
            "last_time": record.get("last_time"),
        }
        actual = {
            "first_date": envelope.get("first_date"),
            "first_time": envelope.get("first_time"),
            "last_date": envelope.get("last_date"),
            "last_time": envelope.get("last_time"),
        }
        mismatch = original != actual
        if mismatch:
            mismatches.append(
                {
                    "source_name": source_name,
                    "data_plane_envelope": original,
                    "semantic_manifest_envelope": actual,
                    "state": "DATA_PLANE_ENVELOPE_DIFFERS_FROM_SEMANTIC_MANIFEST",
                }
            )

        record["data_plane_date_envelope_original"] = original
        record["semantic_manifest_date_envelope"] = {
            **actual,
            "ticker_day_object_count": envelope.get("ticker_day_object_count"),
        }
        record["date_envelope_authority"] = "GOVERNED_SEMANTIC_MANIFEST_ACTUAL_CHRONOLOGY"
        record["date_envelope_reconciliation_state"] = "MISMATCH_PRESERVED_AND_RECONCILED" if mismatch else "MATCH"
        record.update(actual)
        records.append(record)

    records.sort(
        key=lambda row: (
            str(row.get("first_date") or "9999-99-99"),
            str(row.get("first_time") or "99:99:99"),
            str(row.get("source_name") or ""),
            str(row.get("source_drive_id") or ""),
        )
    )

    previous: dict[str, Any] | None = None
    for index, record in enumerate(records):
        first_date = str(record.get("first_date") or "")
        last_date = str(record.get("last_date") or "")
        if not first_date or not last_date or first_date > last_date:
            raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_DATE_ENVELOPE_INVALID:{record.get('source_name')}")
        if previous is not None:
            prev_last = str(previous.get("last_date") or "")
            if prev_last and prev_last >= first_date:
                raise RuntimeError(
                    "SOURCE_UNIVERSE_SEMANTIC_DATE_OVERLAP_OR_CONFLICT:"
                    f"{previous.get('source_name')}:{prev_last}:{record.get('source_name')}:{first_date}"
                )
        ordering = dict(record.get("ordering_key") or {})
        ordering.update(
            {
                "index": index,
                "first_date": record.get("first_date"),
                "first_time": record.get("first_time"),
                "source_name": record.get("source_name"),
                "source_drive_id": record.get("source_drive_id"),
            }
        )
        record["ordering_key"] = ordering
        previous = record

    out["sources"] = records
    out["source_names_in_order"] = [str(row.get("source_name") or "") for row in records]
    out["semantic_date_envelope_reconciliation"] = {
        "schema": SCHEMA,
        "status": "PASS",
        "source_count": len(records),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "rule": "ACTUAL_GOVERNED_SEMANTIC_MANIFEST_CHRONOLOGY_CONTROLS_RUNTIME_DATE_MEMBERSHIP; DATA_PLANE_ENVELOPE_MISMATCH_IS_PRESERVED_AS_DATA_QUALITY_EVIDENCE",
    }
    out.pop("manifest_digest", None)
    out["manifest_digest"] = _digest(out)
    if not manifest_digest_is_valid(out):
        raise RuntimeError("SOURCE_UNIVERSE_SEMANTIC_RECONCILE_OUTPUT_DIGEST_FAIL")
    return out


def collect_semantic_envelopes(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    api = build_drive_api(read_write=False)
    envelopes: dict[str, dict[str, Any]] = {}
    for record in manifest.get("sources", []):
        source_name = str(record.get("source_name") or "")
        if not source_name:
            raise RuntimeError("SOURCE_UNIVERSE_SEMANTIC_SOURCE_NAME_MISSING")
        if source_name in envelopes:
            raise RuntimeError(f"SOURCE_UNIVERSE_SEMANTIC_DUPLICATE_SOURCE_NAME:{source_name}")
        reader = GovernedSourceReader(api, source_name=source_name)
        envelopes[source_name] = _semantic_envelope(reader)
    return envelopes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = _load_manifest(args.manifest)
    envelopes = collect_semantic_envelopes(manifest)
    reconciled = reconcile_manifest_date_envelopes(manifest, envelopes)
    args.output.write_text(json.dumps(reconciled, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    proof = reconciled["semantic_date_envelope_reconciliation"]
    print(
        json.dumps(
            {
                "schema": proof["schema"],
                "status": proof["status"],
                "source_count": proof["source_count"],
                "mismatch_count": proof["mismatch_count"],
                "manifest_digest": reconciled["manifest_digest"],
                "first_source": reconciled["sources"][0]["source_name"] if reconciled.get("sources") else None,
                "first_date": reconciled["sources"][0]["first_date"] if reconciled.get("sources") else None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
