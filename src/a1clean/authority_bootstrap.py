from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .google_drive import build_docs_api

SCHEMA = "A1_CLEAN_AUTHORITY_BOOTSTRAP_V1"
PROOF_SCHEMA = "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1"
DEFAULT_MANIFEST = Path("governance/a1-clean-authority-bootstrap-current.json")
DEFAULT_LOCK = Path("governance/a1-clean-active-authority-lock.json")

_REQUEST_BINDINGS = (
    ("master_handbook", "master_handbook_document_id", "master_handbook_revision_id"),
    ("source_capture", "source_capture_handbook_document_id", "source_capture_handbook_revision_id"),
    ("formula_research", "formula_research_handbook_document_id", "formula_research_handbook_revision_id"),
    ("behavior_reading", "behavior_handbook_document_id", "behavior_handbook_revision_id"),
    ("github_automation", "github_automation_handbook_document_id", "github_automation_handbook_revision_id"),
    ("stable_transition_bridge", "transition_bridge_document_id", "transition_bridge_revision_id"),
    ("machine1_dispatch_registry", "machine1_dispatch_registry_document_id", "machine1_dispatch_registry_revision_id"),
    ("current_execution", "current_execution_document_id", "current_execution_revision_id"),
)

_REQUIRED_PRESERVATION_TRUE = (
    "dynamic_source_universe_required",
    "fixed_source_count_as_universe_authority_forbidden",
    "fixed_physical_field_whitelist_forbidden",
    "preserve_every_physically_available_authorized_record",
    "preserve_every_physically_available_authorized_field",
    "preserve_raw_field_names_slots_values_and_payload_identity",
    "canonical_mapping_is_additive_not_destructive",
    "unknown_or_unmapped_semantics_must_be_preserved",
    "missing_as_zero_forbidden",
    "synthetic_missing_rows_or_events_forbidden",
    "sampling_for_scientific_scope_forbidden",
    "winner_only_or_positive_only_filtering_forbidden",
    "silent_field_or_row_filtering_forbidden",
    "richest_native_authorized_resolution_required",
    "all_eligible_source_supported_tickers_required",
    "actual_first_to_last_source_supported_observation_required",
    "arbitrary_clock_cutoff_forbidden",
    "full_chronology_required",
    "negative_flat_failure_no_event_rare_unknown_open_and_censored_evidence_required",
    "duplicate_retransmission_correction_out_of_order_gap_reconnect_partial_evidence_preserved",
    "value_and_availability_must_be_separate",
    "known_at_and_hindsight_must_be_separate",
    "lossless_artifact_transport_required_for_large_payloads_when_available",
    "transport_optimization_may_not_reduce_evidence",
    "transport_integrity_proof_required_before_semantic_pass",
    "connector_chat_is_thin_control_plane_after_verified_file_intake",
)

_REQUIRED_DATA_FAMILIES = {
    "SOURCE_PROVIDER_VERSION_CAPABILITY_RIGHTS_ENTITLEMENT",
    "SECURITY_ENTITY_REFERENCE_SYMBOL_CONTINUITY",
    "ALL_TIME_IDENTITIES_SEQUENCE_ORDER_AND_SESSION_PHASE",
    "OHLCV_BAR_HISTORICAL_REPLAY_AT_RICHEST_NATIVE_RESOLUTION",
    "L1_BBO_QUOTE_WHEN_AVAILABLE",
    "TRADE_TICK_TIME_AND_TRADE_AND_SOURCE_DEFINED_AGGRESSOR_WHEN_AVAILABLE",
    "L2_DEPTH_ORDER_BOOK_WHEN_AVAILABLE",
    "TIME_AND_ORDER_QUEUE_REFILL_CANCEL_WHEN_AVAILABLE",
    "BROKER_PARTICIPANT_WHEN_AVAILABLE",
    "FOREIGN_OR_PROVIDER_DEFINED_FLOW_WHEN_AVAILABLE",
    "AUCTION_IEP_IEV_PRICE_LIMIT_FCA_AND_MARKET_MECHANISM_WHEN_AVAILABLE",
    "BENCHMARK_INDEX_SECTOR_AND_MARKET_CONTEXT_WHEN_AVAILABLE",
    "CORPORATE_ACTION_AND_SECURITY_CONTINUITY_WHEN_AVAILABLE",
    "QUALITY_GAP_DUPLICATE_ORDER_RECONNECT_STALE_PARTIAL_AVAILABILITY",
    "RETENTION_REPLAYABILITY_AND_SOURCE_RIGHTS",
    "FILE_HASH_READBACK_RUN_AND_PROVENANCE",
    "OPERATIONAL_CONTROL_CHECKPOINT_AND_RESULT_CHANNELS",
    "UNKNOWN_FUTURE_PROVIDER_SPECIFIC_PHYSICAL_FIELDS_AND_RECORD_FAMILIES",
}


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(obj: Any) -> str:
    return _sha256_bytes(_canon(obj).encode("utf-8"))


def _load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError(f"AUTHORITY_BOOTSTRAP_JSON_OBJECT_REQUIRED:{path.as_posix()}")
    return obj


def validate_bootstrap_contract(manifest: dict[str, Any], lock: dict[str, Any]) -> None:
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "ACTIVE":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_MANIFEST_NOT_ACTIVE")
    for key in (
        "full_authority_read_required",
        "google_docs_full_structured_payload_required",
        "exact_document_revision_match_required",
        "summary_or_chat_memory_may_not_substitute",
        "fail_closed_on_missing_unreadable_or_revision_drift",
        "renew_before_source_discovery",
        "renew_before_heavy_compute",
        "renew_before_durable_mutation",
        "reader_only_authority_access_required",
    ):
        if manifest.get(key) is not True:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_REQUIRED_FLAG_FAIL:{key}")

    if lock.get("schema") != "A1_CLEAN_ACTIVE_AUTHORITY_LOCK_V1" or lock.get("status") != "ACTIVE":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_ACTIVE_LOCK_FAIL")
    for key in (
        "prestart_completeness_gate_required",
        "dynamic_source_universe_required",
        "fixed_source_count_as_invariant_forbidden",
        "renewable_authority_sync_required",
        "full_read_new_or_resumed_chat_required",
    ):
        if lock.get(key) is not True:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_LOCK_FLAG_FAIL:{key}")
    if lock.get("formula_stage") != "CLOSED":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_FORMULA_STAGE_NOT_CLOSED")

    preservation = dict(manifest.get("data_preservation_contract") or {})
    for key in _REQUIRED_PRESERVATION_TRUE:
        if preservation.get(key) is not True:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DATA_PRESERVATION_FLAG_FAIL:{key}")
    if preservation.get("unknown_semantic_state") != "PHYSICAL_UNKNOWN_SEMANTIC":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_UNKNOWN_SEMANTIC_STATE_FAIL")

    families = set(str(x) for x in manifest.get("required_open_ended_data_families", []))
    missing_families = sorted(_REQUIRED_DATA_FAMILIES - families)
    if missing_families:
        raise RuntimeError("AUTHORITY_BOOTSTRAP_DATA_FAMILY_GAP:" + ",".join(missing_families))

    availability = set(str(x) for x in manifest.get("explicit_availability_states", []))
    for required in ("AVAILABLE", "UNAVAILABLE", "STALE", "UNSUPPORTED", "UNKNOWN", "UNMAPPED", "PHYSICAL_UNKNOWN_SEMANTIC", "ROUTING_PENDING"):
        if required not in availability:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_AVAILABILITY_STATE_GAP:{required}")

    scientific = dict(manifest.get("machine2_scientific_scope") or {})
    for key in (
        "independent_full_depth_engine_required",
        "same_maximum_source_supported_completeness_target_as_machine1",
        "division_of_labor_as_scientific_design_forbidden",
        "cross_machine_disagreement_preserved",
        "machine_specific_coverage_gap_explicit",
    ):
        if scientific.get(key) is not True:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_SCIENTIFIC_SCOPE_FAIL:{key}")
    if scientific.get("formula_stage") != "CLOSED":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_SCIENTIFIC_FORMULA_STAGE_FAIL")

    docs = list(manifest.get("authority_documents_in_required_read_order") or [])
    if not docs or any(row.get("required") is not True for row in docs):
        raise RuntimeError("AUTHORITY_BOOTSTRAP_DOCUMENT_ORDER_OR_REQUIRED_FLAG_FAIL")
    keys = [str(row.get("key") or "") for row in docs]
    if len(keys) != len(set(keys)) or any(not key for key in keys):
        raise RuntimeError("AUTHORITY_BOOTSTRAP_DOCUMENT_KEY_CARDINALITY_FAIL")


def _resolve_document_binding(row: dict[str, Any], lock: dict[str, Any]) -> tuple[str, str]:
    source = str(row.get("source") or "")
    if source == "authority_lock":
        node = dict((lock.get("documents") or {}).get(str(row.get("key") or "")) or {})
        document_id = str(node.get("document_id") or "")
        revision_id = str(node.get("revision_id") or "")
    elif source == "explicit":
        document_id = str(row.get("document_id") or "")
        revision_id = str(row.get("revision_id") or "")
    else:
        raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DOCUMENT_SOURCE_UNKNOWN:{source}")
    if not document_id or not revision_id:
        raise RuntimeError(f"AUTHORITY_BOOTSTRAP_DOCUMENT_BINDING_MISSING:{row.get('key')}")
    return document_id, revision_id


def _collect_text_runs(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        text_run = node.get("textRun")
        if isinstance(text_run, dict):
            content = text_run.get("content")
            if isinstance(content, str):
                out.append(content)
        for key, value in node.items():
            if key != "textRun":
                _collect_text_runs(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_text_runs(value, out)


def _read_full_document(docs_api: Any, document_id: str) -> dict[str, Any]:
    try:
        return docs_api.documents().get(documentId=document_id, includeTabsContent=True).execute()
    except TypeError:
        return docs_api.documents().get(documentId=document_id).execute()


def _validate_request_against_lock(request: dict[str, Any], lock: dict[str, Any], holds: list[dict[str, Any]]) -> None:
    if request.get("formula_stage") != "CLOSED":
        holds.append({"reason": "REQUEST_FORMULA_STAGE_NOT_CLOSED"})
    for key in (
        "prestart_completeness_gate_required",
        "renewable_authority_sync_required",
        "dynamic_source_universe_required",
        "fixed_source_count_as_universe_authority_forbidden",
        "full_source_supported_observation_envelope",
        "all_source_columns_retrievable_required",
    ):
        if request.get(key) is not True:
            holds.append({"reason": "REQUEST_REQUIRED_FLAG_FAIL", "key": key})
    for key in ("manual_labels_used_as_hidden_targets", "arbitrary_thresholds_added", "missing_as_zero"):
        if request.get(key) is not False:
            holds.append({"reason": "REQUEST_PROHIBITION_FLAG_FAIL", "key": key})

    documents = dict(lock.get("documents") or {})
    for lock_key, id_field, revision_field in _REQUEST_BINDINGS:
        if id_field not in request and revision_field not in request:
            continue
        expected = dict(documents.get(lock_key) or {})
        if str(request.get(id_field) or "") != str(expected.get("document_id") or ""):
            holds.append({"reason": "REQUEST_AUTHORITY_DOCUMENT_ID_DRIFT", "authority": lock_key})
        if str(request.get(revision_field) or "") != str(expected.get("revision_id") or ""):
            holds.append({"reason": "REQUEST_AUTHORITY_REVISION_DRIFT", "authority": lock_key})


def _validate_repo_state(path: Path, obj: dict[str, Any], lock: dict[str, Any], holds: list[dict[str, Any]]) -> None:
    posix = path.as_posix()
    if posix == "governance/a1-clean-active-authority-lock.json":
        if obj.get("status") != "ACTIVE" or obj.get("formula_stage") != "CLOSED":
            holds.append({"reason": "ACTIVE_AUTHORITY_LOCK_STATE_FAIL", "path": posix})
    elif posix == "v32-full-observation-behavior-requests/current.json":
        _validate_request_against_lock(obj, lock, holds)
    elif posix == "v32-behavior-grouping-requests/current.json":
        if obj.get("formula_stage") != "CLOSED":
            holds.append({"reason": "GROUPING_REQUEST_FORMULA_STAGE_NOT_CLOSED", "path": posix})
        if obj.get("dynamic_source_universe_required") is not True:
            holds.append({"reason": "GROUPING_REQUEST_DYNAMIC_SOURCE_REQUIRED", "path": posix})
    elif posix == "canonical-current-recovery-requests/current.json":
        for key in ("canonical_promotion_allowed", "raw_write_allowed", "heavy_behavior_research_allowed"):
            if obj.get(key) is not False:
                holds.append({"reason": "RECOVERY_REQUEST_FORBIDDEN_PERMISSION", "path": posix, "key": key})


def build_authority_sync_proof(
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    repo_root: Path,
    docs_api: Any,
    manifest_sha256: str,
    lock_sha256: str,
) -> dict[str, Any]:
    holds: list[dict[str, Any]] = []
    document_evidence: list[dict[str, Any]] = []

    for index, row in enumerate(manifest["authority_documents_in_required_read_order"], start=1):
        key = str(row["key"])
        try:
            document_id, expected_revision = _resolve_document_binding(row, lock)
            doc = _read_full_document(docs_api, document_id)
            text_parts: list[str] = []
            _collect_text_runs(doc, text_parts)
            text = "".join(text_parts)
            observed_revision = str(doc.get("revisionId") or "")
            observed_document_id = str(doc.get("documentId") or document_id)
            if observed_document_id != document_id:
                holds.append({"reason": "AUTHORITY_DOCUMENT_ID_MISMATCH", "key": key})
            if observed_revision != expected_revision:
                holds.append(
                    {
                        "reason": "AUTHORITY_DOCUMENT_REVISION_DRIFT",
                        "key": key,
                        "expected_revision": expected_revision,
                        "observed_revision": observed_revision,
                    }
                )
            if not text.strip():
                holds.append({"reason": "AUTHORITY_DOCUMENT_EMPTY_TEXT", "key": key})
            document_evidence.append(
                {
                    "read_order": index,
                    "key": key,
                    "document_id": document_id,
                    "title": doc.get("title"),
                    "expected_revision": expected_revision,
                    "observed_revision": observed_revision,
                    "full_structured_payload_sha256": _sha256_json(doc),
                    "extracted_text_sha256": _sha256_bytes(text.encode("utf-8")),
                    "extracted_text_utf8_bytes": len(text.encode("utf-8")),
                    "full_read": True,
                }
            )
        except Exception as exc:  # fail closed, but continue the inventory to expose every gap in one run
            holds.append({"reason": "AUTHORITY_DOCUMENT_READ_FAIL", "key": key, "error": f"{type(exc).__name__}:{exc}"})
            document_evidence.append({"read_order": index, "key": key, "full_read": False})

    state_evidence: list[dict[str, Any]] = []
    for rel in manifest["required_repo_state_files"]:
        path = repo_root / str(rel)
        if not path.is_file():
            holds.append({"reason": "REQUIRED_REPO_STATE_MISSING", "path": str(rel)})
            state_evidence.append({"path": str(rel), "full_read": False})
            continue
        try:
            raw = path.read_bytes()
            obj = json.loads(raw.decode("utf-8"))
            if not isinstance(obj, dict):
                raise RuntimeError("JSON_OBJECT_REQUIRED")
            _validate_repo_state(Path(str(rel)), obj, lock, holds)
            state_evidence.append(
                {
                    "path": str(rel),
                    "sha256": _sha256_bytes(raw),
                    "utf8_bytes": len(raw),
                    "schema": obj.get("schema"),
                    "status": obj.get("status"),
                    "full_read": True,
                }
            )
        except Exception as exc:
            holds.append({"reason": "REQUIRED_REPO_STATE_READ_FAIL", "path": str(rel), "error": f"{type(exc).__name__}:{exc}"})
            state_evidence.append({"path": str(rel), "full_read": False})

    corpus_material = {
        "documents": [
            {
                "key": row.get("key"),
                "document_id": row.get("document_id"),
                "observed_revision": row.get("observed_revision"),
                "full_structured_payload_sha256": row.get("full_structured_payload_sha256"),
                "extracted_text_sha256": row.get("extracted_text_sha256"),
            }
            for row in document_evidence
        ],
        "repo_state": [{"path": row.get("path"), "sha256": row.get("sha256")} for row in state_evidence],
        "manifest_sha256": manifest_sha256,
        "lock_sha256": lock_sha256,
    }
    full_read_complete = (
        all(row.get("full_read") is True for row in document_evidence)
        and all(row.get("full_read") is True for row in state_evidence)
        and not holds
    )
    return {
        "schema": PROOF_SCHEMA,
        "status": "PASS" if full_read_complete else "HOLD",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "full_authority_read_complete": full_read_complete,
        "summary_or_chat_memory_used_as_authority": False,
        "drive_access_mode": "READER_ONLY",
        "authority_document_count": len(document_evidence),
        "repo_state_file_count": len(state_evidence),
        "authority_documents": document_evidence,
        "repo_state_files": state_evidence,
        "authority_corpus_sha256": _sha256_json(corpus_material),
        "bootstrap_manifest_sha256": manifest_sha256,
        "active_authority_lock_sha256": lock_sha256,
        "data_preservation_contract_sha256": _sha256_json(manifest["data_preservation_contract"]),
        "required_data_family_registry_sha256": _sha256_json(manifest["required_open_ended_data_families"]),
        "formula_stage": "CLOSED",
        "holds": holds,
        "next_gate": "SOURCE_UNIVERSE_DISCOVERY" if full_read_complete else "HOLD_AUTHORITY_RECONCILIATION_REQUIRED",
    }


def run_authority_bootstrap(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    authority_lock_path: Path = DEFAULT_LOCK,
    output_path: Path | None = None,
    repo_root: Path = Path("."),
    docs_api: Any | None = None,
) -> dict[str, Any]:
    manifest_raw = manifest_path.read_bytes()
    lock_raw = authority_lock_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8"))
    lock = json.loads(lock_raw.decode("utf-8"))
    validate_bootstrap_contract(manifest, lock)
    api = docs_api if docs_api is not None else build_docs_api()
    proof = build_authority_sync_proof(
        manifest=manifest,
        lock=lock,
        repo_root=repo_root,
        docs_api=api,
        manifest_sha256=_sha256_bytes(manifest_raw),
        lock_sha256=_sha256_bytes(lock_raw),
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return proof


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--authority-lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    proof = run_authority_bootstrap(
        manifest_path=args.manifest,
        authority_lock_path=args.authority_lock,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "schema": proof["schema"],
                "status": proof["status"],
                "full_authority_read_complete": proof["full_authority_read_complete"],
                "authority_document_count": proof["authority_document_count"],
                "repo_state_file_count": proof["repo_state_file_count"],
                "authority_corpus_sha256": proof["authority_corpus_sha256"],
                "hold_count": len(proof["holds"]),
            },
            sort_keys=True,
        )
    )
    return 0 if proof["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
