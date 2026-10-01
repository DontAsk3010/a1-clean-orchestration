from __future__ import annotations

"""Safe one-date continuation for the Machine-2 CURRENT V3 scientific lineage.

This module does not auto-advance.  A durable authorization names the exact
previous DATE_CLOSED boundary only.  The next source/date is derived from the
CURRENT governed semantic manifests, so callers cannot select or skip a date.
A new software/request/manifest identity may be rebound only at that safe
DATE_CLOSED boundary and is persisted with an exact-readback transition proof.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .machine2_current_store import (
    MACHINE2_GOVERNANCE_FOLDER_ID,
    Machine2CurrentStore,
    canonical_json_bytes,
    sha256_bytes,
)
from .m2_current_execution_contract import (
    validate_checkpoint_exact_resume,
    validate_request_for_current_atomic_restart,
)
from .source_universe_manifest import manifest_digest_is_valid, source_names_from_manifest
from . import v32_current_scientific_restart as current


AUTH_SCHEMA = "A1_M2_CURRENT_EXPLICIT_NEXT_DATE_AUTHORIZATION_V1"
TRANSITION_SCHEMA = "A1_M2_CURRENT_DATE_BOUNDARY_TRANSITION_V1"
OPEN_STATE_SCHEMA = "A1_M2_CURRENT_EXPLICIT_NEXT_DATE_OPEN_STATE_V1"
IDENTITY_KEYS = (
    "lineage",
    "request_sha256",
    "software_revision",
    "source_universe_manifest_digest",
    "authority_corpus_sha256",
    "master_document_id",
    "master_revision_id",
    "coverage_matrix_document_id",
    "coverage_matrix_revision_id",
    "old_pass_completion_inherited",
    "old_scientific_checkpoint_read_for_completion",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"M2_NEXT_JSON_NOT_OBJECT:{path}")
    return obj


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity_subset(obj: Mapping[str, Any]) -> dict[str, Any]:
    return {key: obj.get(key) for key in IDENTITY_KEYS}


def _exact_ref(row: Any, position: int) -> dict[str, Any]:
    return {"selection_position": int(position), **dict(row.as_dict())}


def validate_next_date_authorization(auth: Mapping[str, Any]) -> None:
    if auth.get("schema") != AUTH_SCHEMA:
        raise RuntimeError("M2_NEXT_AUTH_SCHEMA_MISMATCH")
    if auth.get("enabled") is not True:
        raise RuntimeError("M2_NEXT_AUTH_DISABLED")
    if auth.get("lineage") != current.LINEAGE:
        raise RuntimeError("M2_NEXT_AUTH_LINEAGE_MISMATCH")
    required_true = (
        "one_date_per_authorization",
        "exact_next_governed_successor_only",
        "arbitrary_target_date_forbidden",
        "prior_checkpoint_must_be_date_closed",
        "fresh_current_prestart_required",
        "identity_rebind_only_at_safe_date_boundary",
        "carry_forward_required",
        "no_auto_advance_after_date_close",
    )
    missing = [key for key in required_true if auth.get(key) is not True]
    if missing:
        raise RuntimeError(f"M2_NEXT_AUTH_CONTRACT_MISMATCH:{missing}")
    if auth.get("formula_stage") != "CLOSED":
        raise RuntimeError("M2_NEXT_FORMULA_STAGE_NOT_CLOSED")
    if auth.get("grouping_stage") != "HOLD":
        raise RuntimeError("M2_NEXT_GROUPING_STAGE_NOT_HOLD")
    if not str(auth.get("expected_last_closed_source") or ""):
        raise RuntimeError("M2_NEXT_EXPECTED_LAST_CLOSED_SOURCE_MISSING")
    if not str(auth.get("expected_last_closed_date") or ""):
        raise RuntimeError("M2_NEXT_EXPECTED_LAST_CLOSED_DATE_MISSING")
    # Intentionally forbidden: the authorization cannot choose the target.
    if any(key in auth for key in ("target_date", "next_date", "target_source", "next_source")):
        raise RuntimeError("M2_NEXT_ARBITRARY_TARGET_FIELD_FORBIDDEN")


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("status") != "PASS" or not manifest_digest_is_valid(manifest):
        raise RuntimeError("M2_NEXT_SOURCE_UNIVERSE_NOT_PASS")
    source_names_from_manifest(manifest, require_pass=True)
    reconciliation = dict(manifest.get("semantic_date_envelope_reconciliation") or {})
    if reconciliation.get("status") != "PASS":
        raise RuntimeError("M2_NEXT_SEMANTIC_DATE_RECONCILIATION_NOT_PASS")


def _validate_reader_identity(reader: Any, record: Mapping[str, Any]) -> None:
    identity = dict(reader.identity.as_dict())
    if str(identity.get("source_drive_id") or "") != str(record.get("source_drive_id") or ""):
        raise RuntimeError("M2_NEXT_SOURCE_ID_DRIFT")
    if str(identity.get("source_sha256") or "") != str(record.get("digest_sha256") or ""):
        raise RuntimeError("M2_NEXT_SOURCE_DIGEST_DRIFT")


def _source_dates(reader: Any) -> list[str]:
    rows = list(reader.semantic_manifest_rows)
    if not rows:
        raise RuntimeError(f"M2_NEXT_SEMANTIC_MANIFEST_EMPTY:{reader.identity.source_name}")
    dates: list[str] = []
    seen: set[str] = set()
    previous: str | None = None
    for row in rows:
        day = str(row.trading_date)
        if previous is not None and day < previous:
            raise RuntimeError(f"M2_NEXT_SEMANTIC_DATE_ORDER_NONMONOTONIC:{reader.identity.source_name}")
        previous = day
        if day not in seen:
            seen.add(day)
            dates.append(day)
    return dates


def resolve_exact_successor(
    manifest: Mapping[str, Any],
    *,
    last_source: str,
    last_date: str,
    reader_factory: Callable[[str], Any],
) -> dict[str, Any] | None:
    """Return exactly one chronological successor; never accepts a target date."""
    _validate_manifest(manifest)
    sequence: list[tuple[str, str]] = []
    readers: dict[str, Any] = {}
    for record in manifest.get("sources", []):
        source_name = str(record.get("source_name") or "")
        reader = reader_factory(source_name)
        readers[source_name] = reader
        _validate_reader_identity(reader, record)
        dates = _source_dates(reader)
        if dates[0] != str(record.get("first_date") or "") or dates[-1] != str(record.get("last_date") or ""):
            raise RuntimeError(f"M2_NEXT_SOURCE_DATE_ENVELOPE_DRIFT:{source_name}")
        sequence.extend((source_name, day) for day in dates)

    if len(sequence) != len(set(sequence)):
        raise RuntimeError("M2_NEXT_DUPLICATE_SOURCE_DATE_IN_SEQUENCE")
    anchors = [i for i, pair in enumerate(sequence) if pair == (last_source, last_date)]
    if len(anchors) != 1:
        raise RuntimeError(f"M2_NEXT_LAST_CLOSED_BOUNDARY_NOT_UNIQUE:{last_source}:{last_date}:{len(anchors)}")
    index = anchors[0]
    if index + 1 >= len(sequence):
        return None

    next_source, next_date = sequence[index + 1]
    reader = readers[next_source]
    selected = [row for row in reader.semantic_manifest_rows if str(row.trading_date) == next_date]
    if not selected:
        raise RuntimeError(f"M2_NEXT_SUCCESSOR_DATE_EMPTY:{next_source}:{next_date}")
    expected_rows = sum(int(row.data_row_count) for row in selected)
    return {
        "source_name": next_source,
        "trading_date": next_date,
        "ticker_day_count": len(selected),
        "source_row_count": expected_rows,
        "first_unit": _exact_ref(selected[0], 0),
        "last_unit": _exact_ref(selected[-1], len(selected) - 1),
    }


def build_rebound_checkpoint(
    checkpoint: Mapping[str, Any],
    *,
    expected_last_source: str,
    expected_last_date: str,
    successor: Mapping[str, Any],
    new_identity: Mapping[str, Any],
    transition_name: str,
) -> dict[str, Any]:
    if checkpoint.get("schema") != current.CHECKPOINT_SCHEMA:
        raise RuntimeError("M2_NEXT_CHECKPOINT_SCHEMA_MISMATCH")
    validate_checkpoint_exact_resume(checkpoint)
    if checkpoint.get("status") != "DATE_CLOSED":
        raise RuntimeError("M2_NEXT_PRIOR_CHECKPOINT_NOT_DATE_CLOSED")
    if str(checkpoint.get("current_source") or "") != expected_last_source:
        raise RuntimeError("M2_NEXT_PRIOR_SOURCE_MISMATCH")
    if str(checkpoint.get("current_date") or "") != expected_last_date:
        raise RuntimeError("M2_NEXT_PRIOR_DATE_MISMATCH")
    if str(checkpoint.get("last_closed_date") or "") != expected_last_date:
        raise RuntimeError("M2_NEXT_LAST_CLOSED_DATE_MISMATCH")
    if not checkpoint.get("date_close"):
        raise RuntimeError("M2_NEXT_PRIOR_DATE_CLOSE_POINTER_MISSING")
    if checkpoint.get("hold") not in (None, {}):
        raise RuntimeError("M2_NEXT_PRIOR_CHECKPOINT_HOLD_PRESENT")

    out = dict(checkpoint)
    previous_date_close = checkpoint.get("date_close")
    out.update(dict(new_identity))
    out.update(
        {
            "status": "IN_PROGRESS",
            "current_source": str(successor["source_name"]),
            "current_date": str(successor["trading_date"]),
            "last_closed_date": expected_last_date,
            "completed_units_in_current_date": 0,
            "completed_source_rows_in_current_date": 0,
            "output_shards": [],
            "last_completed": None,
            "next_exact_resume_point": dict(successor["first_unit"]),
            "hold": None,
            "previous_date_close": previous_date_close,
            "boundary_transition": {"name": transition_name},
            "updated_at_utc": _utc_now(),
        }
    )
    out.pop("date_close", None)
    # carry_by_ticker is deliberately preserved across the date boundary.
    out["carry_by_ticker"] = dict(checkpoint.get("carry_by_ticker") or {})
    validate_checkpoint_exact_resume(out)
    return out


def _already_open_for_successor(
    checkpoint: Mapping[str, Any],
    *,
    expected_last_date: str,
    successor: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> bool:
    return (
        checkpoint.get("status") in {"IN_PROGRESS", "RECONCILING_DATE"}
        and str(checkpoint.get("last_closed_date") or "") == expected_last_date
        and str(checkpoint.get("current_source") or "") == str(successor["source_name"])
        and str(checkpoint.get("current_date") or "") == str(successor["trading_date"])
        and _identity_subset(checkpoint) == dict(identity)
    )


def prepare_explicit_next_date(
    *,
    request_path: Path,
    authorization_path: Path,
    source_universe_manifest_path: Path,
    software_revision: str,
) -> dict[str, Any]:
    if not software_revision or software_revision == "LOCAL_UNVERSIONED":
        raise RuntimeError("M2_NEXT_SOFTWARE_REVISION_REQUIRED")

    request = _load_json(request_path)
    validate_request_for_current_atomic_restart(request)
    auth = _load_json(authorization_path)
    validate_next_date_authorization(auth)
    manifest = _load_json(source_universe_manifest_path)
    _validate_manifest(manifest)

    expected_last_source = str(auth["expected_last_closed_source"])
    expected_last_date = str(auth["expected_last_closed_date"])
    request_sha = _sha256_file(request_path)
    auth_sha = _sha256_file(authorization_path)
    identity = current._checkpoint_identity(
        request=request,
        request_sha256=request_sha,
        manifest=manifest,
        software_revision=software_revision,
    )

    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)
    reader_cache: dict[str, GovernedSourceReader] = {}

    def reader_factory(source_name: str) -> GovernedSourceReader:
        if source_name not in reader_cache:
            reader_cache[source_name] = GovernedSourceReader(reader_api, source_name=source_name)
        return reader_cache[source_name]

    successor = resolve_exact_successor(
        manifest,
        last_source=expected_last_source,
        last_date=expected_last_date,
        reader_factory=reader_factory,
    )
    if successor is None:
        return {
            "status": "CURRENT_HORIZON_NO_SUCCESSOR",
            "execute": False,
            "lineage": current.LINEAGE,
            "last_closed_source": expected_last_source,
            "last_closed_date": expected_last_date,
        }

    store = Machine2CurrentStore(writer_api)
    checkpoint = store.read_json_optional(store.checkpoint_folder_id, current.CHECKPOINT_NAME)
    if checkpoint is None:
        raise RuntimeError("M2_NEXT_CHECKPOINT_MISSING")

    # The same one-date authorization is consumable exactly once.  If its
    # successor is already closed, do not derive/open the following date.
    if (
        checkpoint.get("status") == "DATE_CLOSED"
        and str(checkpoint.get("current_source") or "") == str(successor["source_name"])
        and str(checkpoint.get("current_date") or "") == str(successor["trading_date"])
        and str(checkpoint.get("last_closed_date") or "") == str(successor["trading_date"])
    ):
        return {
            "status": "EXPLICIT_NEXT_DATE_AUTHORIZATION_ALREADY_CONSUMED",
            "execute": False,
            "lineage": current.LINEAGE,
            "source_name": successor["source_name"],
            "trading_date": successor["trading_date"],
        }

    if _already_open_for_successor(
        checkpoint,
        expected_last_date=expected_last_date,
        successor=successor,
        identity=identity,
    ):
        validate_checkpoint_exact_resume(checkpoint)
        return {
            "status": "EXPLICIT_NEXT_DATE_ALREADY_OPEN_RESUME",
            "execute": True,
            "lineage": current.LINEAGE,
            "source_name": successor["source_name"],
            "trading_date": successor["trading_date"],
            "next_exact_resume_point": checkpoint.get("next_exact_resume_point"),
        }

    state = store.read_json_optional(store.current_state_folder_id, current.CURRENT_STATE_NAME)
    if not state:
        raise RuntimeError("M2_NEXT_CURRENT_STATE_MISSING")
    if state.get("status") != "DATE_CLOSED_WAITING_EXPLICIT_NEXT_DATE_AUTHORITY":
        raise RuntimeError("M2_NEXT_CURRENT_STATE_NOT_WAITING_EXPLICIT_AUTHORITY")
    if str(state.get("last_closed_date") or "") != expected_last_date:
        raise RuntimeError("M2_NEXT_CURRENT_STATE_LAST_CLOSED_DATE_MISMATCH")
    if str(state.get("current_source") or "") != expected_last_source:
        raise RuntimeError("M2_NEXT_CURRENT_STATE_SOURCE_MISMATCH")

    previous_checkpoint_sha = sha256_bytes(canonical_json_bytes(checkpoint))
    transition_name = (
        f"{current.LINEAGE}__BOUNDARY__{expected_last_date}__TO__"
        f"{successor['trading_date']}__{software_revision[:12]}.json"
    )
    transition = {
        "schema": TRANSITION_SCHEMA,
        "lineage": current.LINEAGE,
        "status": "PREPARED",
        "authorization_sha256": auth_sha,
        "authorization_name": authorization_path.name,
        "previous_checkpoint_sha256": previous_checkpoint_sha,
        "previous_identity": _identity_subset(checkpoint),
        "new_identity": dict(identity),
        "prior_source": expected_last_source,
        "prior_date": expected_last_date,
        "prior_date_close": checkpoint.get("date_close"),
        "next_source": successor["source_name"],
        "next_date": successor["trading_date"],
        "next_first_unit": successor["first_unit"],
        "next_last_unit": successor["last_unit"],
        "next_ticker_day_count": successor["ticker_day_count"],
        "next_source_row_count": successor["source_row_count"],
        "successor_rule": "EXACT_NEXT_GOVERNED_SEMANTIC_DATE_ONLY_NO_CALLER_TARGET",
        "carry_forward_required": True,
        "formula_stage": "CLOSED",
        "grouping_stage": "HOLD",
        "prepared_at_utc": _utc_now(),
    }
    transition_upload = store.upsert_json(
        folder_id=MACHINE2_GOVERNANCE_FOLDER_ID,
        name=transition_name,
        obj=transition,
    )

    rebound = build_rebound_checkpoint(
        checkpoint,
        expected_last_source=expected_last_source,
        expected_last_date=expected_last_date,
        successor=successor,
        new_identity=identity,
        transition_name=transition_name,
    )
    rebound["boundary_transition"] = {
        "id": transition_upload["id"],
        "name": transition_name,
    }
    checkpoint_upload = store.upsert_json(
        folder_id=store.checkpoint_folder_id,
        name=current.CHECKPOINT_NAME,
        obj=rebound,
    )

    open_state = {
        "schema": OPEN_STATE_SCHEMA,
        "lineage": current.LINEAGE,
        "status": "EXPLICIT_NEXT_DATE_OPEN_IN_PROGRESS",
        "prior_source": expected_last_source,
        "last_closed_date": expected_last_date,
        "current_source": successor["source_name"],
        "current_date": successor["trading_date"],
        "checkpoint_name": current.CHECKPOINT_NAME,
        "boundary_transition": {"id": transition_upload["id"], "name": transition_name},
        "next_date_auto_opened": False,
        "explicit_one_date_authorization_sha256": auth_sha,
        "formula_stage": "CLOSED",
        "grouping_stage": "HOLD",
        "updated_at_utc": _utc_now(),
    }
    state_upload = store.upsert_json(
        folder_id=store.current_state_folder_id,
        name=current.CURRENT_STATE_NAME,
        obj=open_state,
    )

    transition["status"] = "COMMITTED_READBACK_PASS"
    transition["checkpoint_after_rebind"] = checkpoint_upload
    transition["current_state_after_rebind"] = state_upload
    transition["checkpoint_after_rebind_sha256"] = sha256_bytes(canonical_json_bytes(rebound))
    transition["current_state_after_rebind_sha256"] = sha256_bytes(canonical_json_bytes(open_state))
    transition["committed_at_utc"] = _utc_now()
    final_transition_upload = store.upsert_json(
        folder_id=MACHINE2_GOVERNANCE_FOLDER_ID,
        name=transition_name,
        obj=transition,
    )

    readback = store.read_json_optional(store.checkpoint_folder_id, current.CHECKPOINT_NAME)
    if readback is None or readback != rebound:
        raise RuntimeError("M2_NEXT_REBOUND_CHECKPOINT_EXACT_READBACK_FAIL")
    validate_checkpoint_exact_resume(readback)
    if _identity_subset(readback) != dict(identity):
        raise RuntimeError("M2_NEXT_REBOUND_IDENTITY_READBACK_FAIL")

    return {
        "status": "EXPLICIT_NEXT_DATE_BOUNDARY_OPEN_PASS",
        "execute": True,
        "lineage": current.LINEAGE,
        "source_name": successor["source_name"],
        "trading_date": successor["trading_date"],
        "first_unit": successor["first_unit"],
        "ticker_day_count": successor["ticker_day_count"],
        "source_row_count": successor["source_row_count"],
        "boundary_transition": final_transition_upload,
        "checkpoint": checkpoint_upload,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open exactly one governed Machine-2 V3 successor date at a verified DATE_CLOSED boundary.")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--source-universe-manifest", required=True, type=Path)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    result = prepare_explicit_next_date(
        request_path=args.request,
        authorization_path=args.authorization,
        source_universe_manifest_path=args.source_universe_manifest,
        software_revision=args.software_revision,
    )
    args.result.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
