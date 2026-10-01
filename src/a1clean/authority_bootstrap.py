from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .google_drive import build_drive_api

SCHEMA = "A1_CLEAN_AUTHORITY_BOOTSTRAP_V1"
PROOF_SCHEMA = "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1"
DEFAULT_MANIFEST = Path("governance/a1-clean-authority-bootstrap-current.json")
DEFAULT_LOCK = Path("governance/a1-clean-active-authority-lock.json")

_REQUEST_BINDINGS = (
    ("machine2_owner_hard_lock", "owner_hard_lock_document_id", "owner_hard_lock_revision_id"),
    ("master_handbook", "master_handbook_document_id", "master_handbook_revision_id"),
    ("source_capture", "source_capture_handbook_document_id", "source_capture_handbook_revision_id"),
    ("formula_research", "formula_research_handbook_document_id", "formula_research_handbook_revision_id"),
    ("behavior_reading", "behavior_handbook_document_id", "behavior_handbook_revision_id"),
    ("github_automation", "github_automation_handbook_document_id", "github_automation_handbook_revision_id"),
    ("stable_transition_bridge", "transition_bridge_document_id", "transition_bridge_revision_id"),
    ("machine1_dispatch_registry", "machine1_dispatch_registry_document_id", "machine1_dispatch_registry_revision_id"),
    ("current_execution", "current_execution_document_id", "current_execution_revision_id"),
    ("machine2_master_coverage_matrix", "machine2_master_coverage_matrix_document_id", "machine2_master_coverage_matrix_revision_id"),
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

_REQUEST_FULL_DEPTH_TRUE = (
    "owner_hard_lock_full_depth_required",
    "programmatic_processing_allowed",
    "full_source_supported_observation_envelope",
    "all_source_columns_retrievable_required",
    "all_actual_source_supported_1m_rows_required_when_available",
    "missing_minute_as_flat_forbidden",
    "missing_minute_as_zero_forbidden",
    "synthetic_missing_bar_fill_forbidden",
    "sparse_ticker_all_actual_rows_required",
    "primitive_facts_preserved_before_compression",
    "exact_time_known_at_hindsight_separation_required",
    "price_path_location_memory_required",
    "effort_response_nonresponse_required",
    "negative_quiet_failure_contradiction_required",
    "attempts_retests_loops_nested_episodes_required",
    "state_maturity_persistence_decay_required",
    "lead_lag_relationship_graph_required",
    "behavior_lifecycle_required",
    "behavior_path_required",
    "cross_date_continuity_required",
    "open_left_right_censoring_required",
    "market_sector_cross_sectional_context_required_when_source_supported",
    "data_quality_separate_from_market_behavior_required",
    "near_twin_counterexample_required_at_applicable_stage",
    "base_rate_denominator_readiness_required",
    "formation_snapshot_required",
    "formation_known_at_vs_hindsight_wall_required",
    "availability_unknown_true_zero_discipline_required",
    "semantic_label_full_lineage_required",
    "dual_independent_full_depth_research_engines_required",
    "same_maximum_source_supported_completeness_target_required",
)


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(obj: Any) -> str:
    return _sha256_bytes(_canon(obj).encode("utf-8"))


def validate_bootstrap_contract(manifest: dict[str, Any], lock: dict[str, Any]) -> None:
    if manifest.get("schema") != SCHEMA or manifest.get("status") != "ACTIVE":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_MANIFEST_NOT_ACTIVE")
    for key in (
        "full_authority_read_required",
        "google_drive_full_native_text_export_required",
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
        "machine2_owner_hard_lock_full_depth_required",
        "machine2_all_actual_source_supported_1m_rows_required_when_available",
        "machine2_missing_minute_as_flat_forbidden",
        "machine2_missing_minute_as_zero_forbidden",
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
        "programmatic_processing_allowed",
        "programmatic_semantic_state_detection_allowed_with_full_lineage",
        "all_actual_source_supported_1m_rows_required_when_available",
        "missing_minute_as_flat_forbidden",
        "missing_minute_as_zero_forbidden",
        "full_owner_hard_lock_domains_required",
    ):
        if scientific.get(key) is not True:
            raise RuntimeError(f"AUTHORITY_BOOTSTRAP_SCIENTIFIC_SCOPE_FAIL:{key}")
    if scientific.get("current_scientific_lineage") != "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3":
        raise RuntimeError("AUTHORITY_BOOTSTRAP_MACHINE2_LINEAGE_NOT_FULL_DEPTH_V3")
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


def _latest_revision_id(drive_api: Any, document_id: str) -> str:
    revisions: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "fileId": document_id,
            "pageSize": 1000,
            "fields": "nextPageToken,revisions(id,modifiedTime)",
        }
        if token:
            kwargs["pageToken"] = token
        page = drive_api.revisions().list(**kwargs).execute()
        revisions.extend(list(page.get("revisions") or []))
        token = str(page.get("nextPageToken") or "") or None
        if not token:
            break
    if not revisions:
        raise RuntimeError(f"AUTHORITY_DOCUMENT_REVISION_LIST_EMPTY:{document_id}")
    revision_id = str(revisions[-1].get("id") or "")
    if not revision_id:
        raise RuntimeError(f"AUTHORITY_DOCUMENT_REVISION_ID_EMPTY:{document_id}")
    return revision_id


def _read_full_document_via_drive(drive_api: Any, document_id: str) -> dict[str, Any]:
    meta = drive_api.files().get(
        fileId=document_id,
        fields="id,name,mimeType,modifiedTime,version,trashed",
        supportsAllDrives=True,
    ).execute()
    if meta.get("trashed") is True:
        raise RuntimeError(f"AUTHORITY_DOCUMENT_TRASHED:{document_id}")
    if str(meta.get("mimeType") or "") != "application/vnd.google-apps.document":
        raise RuntimeError(f"AUTHORITY_DOCUMENT_NOT_GOOGLE_DOC:{document_id}:{meta.get('mimeType')}")
    exported = drive_api.files().export(fileId=document_id, mimeType="text/plain").execute()
    if isinstance(exported, str):
        raw = exported.encode("utf-8")
    elif isinstance(exported, (bytes, bytearray)):
        raw = bytes(exported)
    else:
        raise RuntimeError(f"AUTHORITY_DOCUMENT_EXPORT_TYPE_FAIL:{document_id}:{type(exported).__name__}")
    text = raw.decode("utf-8-sig")
    if not text.strip():
        raise RuntimeError(f"AUTHORITY_DOCUMENT_EMPTY_TEXT:{document_id}")
    return {
        "metadata": meta,
        "latest_revision_id": _latest_revision_id(drive_api, document_id),
        "raw": raw,
        "text": text,
    }


def _validate_request_against_lock(request: dict[str, Any], lock: dict[str, Any], holds: list[dict[str, Any]]) -> None:
    if request.get("formula_stage") != "CLOSED":
        holds.append({"reason": "REQUEST_FORMULA_STAGE_NOT_CLOSED"})
    for key in (
        "prestart_completeness_gate_required",
        "renewable_authority_sync_required",
        "dynamic_source_universe_required",
        "fixed_source_count_as_universe_authority_forbidden",
        *_REQUEST_FULL_DEPTH_TRUE,
    ):
        if request.get(key) is not True:
            holds.append({"reason": "REQUEST_REQUIRED_FLAG_FAIL", "key": key})
    for key in (
        "manual_labels_used_as_hidden_targets",
        "arbitrary_thresholds_added",
        "missing_as_zero",
        "sampling_used",
        "winner_only_filtering_used",
        "summary_only_substitution_used",
        "prior_v1_v2_scientific_completion_inherited",
    ):
        if request.get(key) is not False:
            holds.append({"reason": "REQUEST_PROHIBITION_FLAG_FAIL", "key": key})
    if request.get("current_scientific_lineage") != "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3":
        holds.append({"reason": "REQUEST_MACHINE2_LINEAGE_NOT_FULL_DEPTH_V3"})
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
    drive_api: Any,
    manifest_sha256: str,
    lock_sha256: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    validate_bootstrap_contract(manifest, lock)
    holds: list[dict[str, Any]] = []
    doc_proofs: list[dict[str, Any]] = []
    for row in manifest.get("authority_documents_in_required_read_order", []):
        key = str(row.get("key") or "")
        expected_drive_revision = str(row.get("drive_revision_id") or "")
        document_id, revision_id = _resolve_document_binding(row, lock)
        try:
            full = _read_full_document_via_drive(drive_api, document_id)
            latest_revision = str(full["latest_revision_id"])
            revision_match = latest_revision == expected_drive_revision
            if not revision_match:
                holds.append(
                    {
                        "reason": "AUTHORITY_DOCUMENT_REVISION_DRIFT",
                        "key": key,
                        "expected_revision": expected_drive_revision,
                        "observed_revision": latest_revision,
                    }
                )
            doc_proofs.append(
                {
                    "key": key,
                    "document_id": document_id,
                    "authority_lock_revision_id": revision_id,
                    "expected_revision": expected_drive_revision,
                    "observed_revision": latest_revision,
                    "revision_match": revision_match,
                    "full_read": True,
                    "byte_count": len(full["raw"]),
                    "text_char_count": len(full["text"]),
                    "sha256": _sha256_bytes(full["raw"]),
                    "modified_time": full["metadata"].get("modifiedTime"),
                    "drive_version": full["metadata"].get("version"),
                }
            )
        except Exception as exc:
            holds.append({"reason": "AUTHORITY_DOCUMENT_READ_FAIL", "key": key, "error": f"{type(exc).__name__}:{exc}"})
            doc_proofs.append(
                {
                    "key": key,
                    "document_id": document_id,
                    "authority_lock_revision_id": revision_id,
                    "expected_revision": expected_drive_revision,
                    "full_read": False,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    repo_proofs: list[dict[str, Any]] = []
    for rel in manifest.get("required_repo_state_files", []):
        path = repo_root / str(rel)
        if not path.is_file():
            holds.append({"reason": "REPO_STATE_FILE_MISSING", "path": str(rel)})
            repo_proofs.append({"path": str(rel), "full_read": False})
            continue
        raw = path.read_bytes()
        try:
            obj = json.loads(raw.decode("utf-8-sig")) if path.suffix.lower() == ".json" else {"status": "NON_JSON_FULL_READ"}
        except Exception as exc:
            holds.append({"reason": "REPO_STATE_FILE_PARSE_FAIL", "path": str(rel), "error": f"{type(exc).__name__}:{exc}"})
            repo_proofs.append({"path": str(rel), "full_read": True, "sha256": _sha256_bytes(raw), "parse_ok": False})
            continue
        _validate_repo_state(path.relative_to(repo_root), obj, lock, holds)
        repo_proofs.append(
            {
                "path": str(rel),
                "full_read": True,
                "parse_ok": True,
                "byte_count": len(raw),
                "sha256": _sha256_bytes(raw),
            }
        )

    return {
        "schema": PROOF_SCHEMA,
        "status": "PASS" if not holds else "HOLD",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "manifest_sha256": manifest_sha256,
        "active_authority_lock_sha256": lock_sha256,
        "authority_documents": doc_proofs,
        "repo_state_files": repo_proofs,
        "data_preservation_contract_sha256": _sha256_json(manifest.get("data_preservation_contract")),
        "machine2_scientific_scope_sha256": _sha256_json(manifest.get("machine2_scientific_scope")),
        "full_authority_read_complete": not holds,
        "holds": holds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="A1 CLEAN fresh-current authority sync proof")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    manifest_path = (repo_root / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest)
    lock_path = (repo_root / args.lock).resolve() if not Path(args.lock).is_absolute() else Path(args.lock)
    out_path = Path(args.out).resolve()

    manifest_raw = manifest_path.read_bytes()
    lock_raw = lock_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8-sig"))
    lock = json.loads(lock_raw.decode("utf-8-sig"))
    drive_api = build_drive_api()
    proof = build_authority_sync_proof(
        manifest=manifest,
        lock=lock,
        repo_root=repo_root,
        drive_api=drive_api,
        manifest_sha256=_sha256_bytes(manifest_raw),
        lock_sha256=_sha256_bytes(lock_raw),
        run_id=args.run_id,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": proof["status"], "holds": proof["holds"], "out": str(out_path)}, indent=2))
    return 0 if proof["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
