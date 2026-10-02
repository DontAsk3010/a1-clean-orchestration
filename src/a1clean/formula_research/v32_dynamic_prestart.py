from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .source_universe_manifest import manifest_digest_is_valid, source_names_from_manifest

_REQUEST_AUTHORITY_BINDINGS = (
    ("master_handbook_document_id", "master_handbook_revision_id", "master_handbook"),
    ("source_capture_handbook_document_id", "source_capture_handbook_revision_id", "source_capture"),
    ("formula_research_handbook_document_id", "formula_research_handbook_revision_id", "formula_research"),
    ("behavior_handbook_document_id", "behavior_handbook_revision_id", "behavior_reading"),
    ("github_automation_handbook_document_id", "github_automation_handbook_revision_id", "github_automation"),
    ("transition_bridge_document_id", "transition_bridge_revision_id", "stable_transition_bridge"),
    ("machine1_dispatch_registry_document_id", "machine1_dispatch_registry_revision_id", "machine1_dispatch_registry"),
    ("current_execution_document_id", "current_execution_revision_id", "current_execution"),
)

_FULL_OBSERVATION_RESTART_TRUE = (
    "machine2_full_scientific_restart_from_beginning_required",
    "canonical_raw_physical_reuse_after_current_integrity_proof_only",
    "strict_governed_chronological_restart_required",
    "progressive_current_checkpoint_lineage_must_start_new",
    "date_ticker_record_timestamp_exact_resume_checkpoint_required",
    "per_source_only_checkpoint_is_not_sufficient_for_exact_resume",
    "all_current_master_required_layers_reread_rederive_recompute_or_explicitly_revalidate_from_beginning",
)

_FULL_OBSERVATION_RESTART_FALSE = (
    "old_pass_may_skip_current_reading_unit",
    "old_derived_semantic_checkpoint_completion_inherited",
    "sunk_compute_or_old_completion_exception_allowed",
)

_LOCK_RESTART_TRUE = (
    "machine2_owner_explicit_full_scientific_restart_from_beginning_required",
    "machine2_canonical_raw_physical_reuse_only_after_current_integrity_proof",
    "machine2_strict_chronological_restart_required",
    "machine2_progressive_current_checkpoint_lineage_must_start_new",
    "machine2_heavy_run_requires_restart_contract_prestart_pass",
)

_LOCK_RESTART_FALSE = (
    "machine2_old_scientific_pass_may_skip_current_reading_unit",
    "machine2_old_derived_semantic_checkpoint_completion_inherited",
    "machine2_sunk_cost_exception_allowed",
)

_EXACT_MACHINE2_RUNNER = "A1-WINDOWS-COMPUTE-02"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_full_observation_request(request: dict[str, Any]) -> bool:
    return str(request.get("schema") or "").startswith("A1_V32_FULL_OBSERVATION_BEHAVIOR_REQUEST_")


def _validate_full_restart_contract(request: dict[str, Any], lock: dict[str, Any]) -> None:
    for key in _LOCK_RESTART_TRUE:
        if lock.get(key) is not True:
            raise RuntimeError(f"PRESTART_LOCK_MACHINE2_RESTART_FLAG_FAIL:{key}")
    for key in _LOCK_RESTART_FALSE:
        if lock.get(key) is not False:
            raise RuntimeError(f"PRESTART_LOCK_MACHINE2_RESTART_PROHIBITION_FAIL:{key}")
    if lock.get("machine2_old_scientific_pass_current_compliance") != "NONE_ACCEPTED":
        raise RuntimeError("PRESTART_LOCK_OLD_PASS_CURRENT_COMPLIANCE_FAIL")
    if lock.get("machine2_scientific_restart_cursor_authority") != (
        "EARLIEST_GOVERNED_SOURCE_DATE_TICKER_OBSERVATION_FROM_DYNAMIC_SOURCE_DISCOVERY"
    ):
        raise RuntimeError("PRESTART_LOCK_RESTART_CURSOR_AUTHORITY_FAIL")

    for key in _FULL_OBSERVATION_RESTART_TRUE:
        if request.get(key) is not True:
            raise RuntimeError(f"PRESTART_REQUEST_MACHINE2_RESTART_FLAG_FAIL:{key}")
    for key in _FULL_OBSERVATION_RESTART_FALSE:
        if request.get(key) is not False:
            raise RuntimeError(f"PRESTART_REQUEST_MACHINE2_RESTART_PROHIBITION_FAIL:{key}")
    if request.get("old_pass_current_compliance") != "NONE_ACCEPTED":
        raise RuntimeError("PRESTART_REQUEST_OLD_PASS_CURRENT_COMPLIANCE_FAIL")
    if request.get("scientific_restart_cursor_authority") != (
        "EARLIEST_GOVERNED_SOURCE_DATE_TICKER_OBSERVATION_FROM_DYNAMIC_SOURCE_DISCOVERY"
    ):
        raise RuntimeError("PRESTART_REQUEST_RESTART_CURSOR_AUTHORITY_FAIL")
    if request.get("no_pass_claim") is not True:
        raise RuntimeError("PRESTART_REQUEST_NO_PASS_CLAIM_FAIL")

    # CURRENT Automation authority requires PRESTART itself to fail closed until
    # GitHub's scheduler is bound to a server-side selector that resolves only
    # the exact Machine-2 runner. A post-scheduling RUNNER_NAME check is not a
    # substitute for deterministic routing proof.
    if request.get("deterministic_exact_runner_routing_required") is not True:
        raise RuntimeError("PRESTART_REQUEST_DETERMINISTIC_ROUTING_REQUIREMENT_MISSING")
    if request.get("deterministic_exact_runner_routing_proven") is not True:
        raise RuntimeError("PRESTART_REQUEST_DETERMINISTIC_ROUTING_NOT_PROVEN")
    if str(request.get("deterministic_exact_runner_name") or "") != _EXACT_MACHINE2_RUNNER:
        raise RuntimeError("PRESTART_REQUEST_EXACT_RUNNER_IDENTITY_DRIFT")
    if not str(request.get("deterministic_exact_runner_selector") or ""):
        raise RuntimeError("PRESTART_REQUEST_DETERMINISTIC_ROUTING_SELECTOR_MISSING")
    if not str(request.get("deterministic_exact_runner_routing_proof_sha256") or ""):
        raise RuntimeError("PRESTART_REQUEST_DETERMINISTIC_ROUTING_PROOF_DIGEST_MISSING")

    documents = dict(lock.get("documents") or {})
    matrix = dict(documents.get("machine2_master_coverage_matrix") or {})
    if not matrix:
        raise RuntimeError("PRESTART_MACHINE2_COVERAGE_MATRIX_LOCK_MISSING")
    if str(request.get("machine2_master_coverage_matrix_document_id") or "") != str(
        matrix.get("document_id") or ""
    ):
        raise RuntimeError("PRESTART_MACHINE2_COVERAGE_MATRIX_DOCUMENT_ID_DRIFT")
    if str(request.get("machine2_master_coverage_matrix_revision_id") or "") != str(
        matrix.get("revision_id") or ""
    ):
        raise RuntimeError("PRESTART_MACHINE2_COVERAGE_MATRIX_REVISION_DRIFT")


def validate_dynamic_prestart(
    *,
    request: dict[str, Any],
    lock: dict[str, Any],
    source_universe: dict[str, Any],
    require_enabled: bool,
) -> dict[str, Any]:
    if lock.get("schema") != "A1_CLEAN_ACTIVE_AUTHORITY_LOCK_V1" or lock.get("status") != "ACTIVE":
        raise RuntimeError("PRESTART_ACTIVE_AUTHORITY_LOCK_FAIL")
    for key in (
        "prestart_completeness_gate_required",
        "dynamic_source_universe_required",
        "fixed_source_count_as_invariant_forbidden",
        "renewable_authority_sync_required",
    ):
        if lock.get(key) is not True:
            raise RuntimeError(f"PRESTART_LOCK_FLAG_FAIL:{key}")
    if request.get("prestart_completeness_gate_required") is not True:
        raise RuntimeError("PRESTART_REQUEST_GATE_FLAG_FAIL")
    if request.get("dynamic_source_universe_required") is not True:
        raise RuntimeError("PRESTART_REQUEST_DYNAMIC_SOURCE_FLAG_FAIL")
    if request.get("fixed_source_count_as_universe_authority_forbidden") is not True:
        raise RuntimeError("PRESTART_REQUEST_FIXED_COUNT_PROHIBITION_FAIL")
    if request.get("renewable_authority_sync_required") is not True:
        raise RuntimeError("PRESTART_REQUEST_RENEWABLE_AUTHORITY_FAIL")
    if require_enabled and request.get("enabled") is not True:
        raise RuntimeError("PRESTART_REQUEST_DISABLED_HOLD")
    if request.get("formula_stage") != "CLOSED" or lock.get("formula_stage") != "CLOSED":
        raise RuntimeError("PRESTART_FORMULA_STAGE_NOT_CLOSED")

    documents = dict(lock.get("documents") or {})
    for id_field, revision_field, lock_key in _REQUEST_AUTHORITY_BINDINGS:
        if id_field not in request and revision_field not in request:
            continue
        node = dict(documents.get(lock_key) or {})
        if str(request.get(id_field) or "") != str(node.get("document_id") or ""):
            raise RuntimeError(f"PRESTART_AUTHORITY_DOCUMENT_ID_DRIFT:{lock_key}")
        if str(request.get(revision_field) or "") != str(node.get("revision_id") or ""):
            raise RuntimeError(f"PRESTART_AUTHORITY_REVISION_DRIFT:{lock_key}")

    if _is_full_observation_request(request):
        _validate_full_restart_contract(request, lock)

    if not manifest_digest_is_valid(source_universe):
        raise RuntimeError("PRESTART_SOURCE_UNIVERSE_DIGEST_FAIL")
    authority_sync = source_universe.get("authority_sync")
    if not isinstance(authority_sync, dict):
        raise RuntimeError("PRESTART_AUTHORITY_SYNC_PROOF_MISSING")
    if authority_sync.get("schema") != "A1_CLEAN_AUTHORITY_SYNC_PROOF_V1":
        raise RuntimeError("PRESTART_AUTHORITY_SYNC_SCHEMA_FAIL")
    if authority_sync.get("status") != "PASS" or authority_sync.get("full_authority_read_complete") is not True:
        raise RuntimeError("PRESTART_AUTHORITY_SYNC_NOT_PASS")
    for key in (
        "authority_corpus_sha256",
        "bootstrap_manifest_sha256",
        "active_authority_lock_sha256",
        "data_preservation_contract_sha256",
        "required_data_family_registry_sha256",
    ):
        if not str(authority_sync.get(key) or ""):
            raise RuntimeError(f"PRESTART_AUTHORITY_SYNC_FINGERPRINT_MISSING:{key}")

    names = source_names_from_manifest(source_universe, require_pass=True)
    if int(source_universe.get("source_count", -1)) != len(names):
        raise RuntimeError("PRESTART_SOURCE_UNIVERSE_COUNT_DRIFT")

    result = {
        "status": "PASS",
        "request_schema": request.get("schema"),
        "request_enabled": request.get("enabled"),
        "source_universe_count": len(names),
        "source_universe_manifest_digest": source_universe.get("manifest_digest"),
        "authority_sync_status": authority_sync.get("status"),
        "authority_corpus_sha256": authority_sync.get("authority_corpus_sha256"),
        "next_source_authority": "SOURCE_UNIVERSE_MANIFEST",
        "fixed_source_count_invariant_used": False,
        "machine2_full_scientific_restart_from_beginning_required": bool(
            request.get("machine2_full_scientific_restart_from_beginning_required")
        ),
        "old_pass_skip_allowed": bool(request.get("old_pass_may_skip_current_reading_unit")),
        "formula_stage": "CLOSED",
    }
    if _is_full_observation_request(request):
        result.update(
            {
                "deterministic_exact_runner_routing_proven": True,
                "deterministic_exact_runner_name": request.get("deterministic_exact_runner_name"),
                "deterministic_exact_runner_selector": request.get("deterministic_exact_runner_selector"),
                "deterministic_exact_runner_routing_proof_sha256": request.get(
                    "deterministic_exact_runner_routing_proof_sha256"
                ),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--authority-lock", type=Path, default=Path("governance/a1-clean-active-authority-lock.json"))
    parser.add_argument("--source-universe-manifest", type=Path, required=True)
    parser.add_argument("--require-enabled", action="store_true")
    args = parser.parse_args()
    result = validate_dynamic_prestart(
        request=_load(args.request),
        lock=_load(args.authority_lock),
        source_universe=_load(args.source_universe_manifest),
        require_enabled=args.require_enabled,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
