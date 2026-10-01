from __future__ import annotations

"""CURRENT entrypoint for Machine-2 full-depth scientific restart.

V1 and V2 restart artifacts remain historical/audit evidence only for CURRENT
completion. The latest OWNER hard lock materially expands and clarifies the
Machine-2 scientific contract: programmatic processing is allowed, but full
source-supported depth, causal lineage, auditable labels, and all mandatory
Master domains must be represented.

Valid canonical RAW/lossless substrate remains reusable after CURRENT integrity
proof. Affected V2 derived/semantic outputs may not advance the V3 cursor.
"""

import json
import os
from pathlib import Path
from typing import Any, Mapping

from . import v32_current_scientific_restart_engine as _engine
from .m2_full_depth_extension_v2 import augment_scientific_object
from .machine2_current_store import (
    MACHINE2_CHECKPOINT_FOLDER_ID,
    MACHINE2_CURRENT_STATE_FOLDER_ID,
    MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
)


PRIOR_LINEAGE = "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V2"
LINEAGE = "MACHINE2_CURRENT_FULL_DEPTH_RESTART_FROM_BEGINNING_V3"
CHECKPOINT_SCHEMA = "A1_M2_CURRENT_FULL_DEPTH_CHECKPOINT_V3"
SCIENTIFIC_OBJECT_SCHEMA = "A1_M2_CURRENT_FULL_DEPTH_TICKER_DAY_OBJECT_V3"
DATE_CLOSE_SCHEMA = "A1_M2_CURRENT_FULL_DEPTH_DATE_CLOSE_V3"
CHECKPOINT_NAME = f"{LINEAGE}__CHECKPOINT_CURRENT.json"
CURRENT_STATE_NAME = f"{LINEAGE}__STATE_CURRENT.json"
OWNER_OVERRIDE_EFFECTIVE_DATE = "2026-10-01"
OWNER_FULL_DEPTH_EXTENSION_ACTIVE = True
OWNER_FULL_DEPTH_EXTENSION_VERSION = "V2_EXACT_TIMESTAMP_ALIGNMENT"
OLD_V1_V2_COMPLETION_INHERITED = False
AUTHORITY_LOCK_PATH = Path("governance/a1-clean-active-authority-lock.json")
AUTHORITY_BOOTSTRAP_PATH = Path("governance/a1-clean-authority-bootstrap-current.json")

_engine.LINEAGE = LINEAGE
_engine.CHECKPOINT_SCHEMA = CHECKPOINT_SCHEMA
_engine.SCIENTIFIC_OBJECT_SCHEMA = SCIENTIFIC_OBJECT_SCHEMA
_engine.DATE_CLOSE_SCHEMA = DATE_CLOSE_SCHEMA
_engine.CHECKPOINT_NAME = CHECKPOINT_NAME
_engine.CURRENT_STATE_NAME = CURRENT_STATE_NAME

_BASE_BUILD_CURRENT_SCIENTIFIC_OBJECT = _engine.build_current_scientific_object
_BASE_CHECKPOINT_IDENTITY = _engine._checkpoint_identity


def _load_repo_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"M2_CURRENT_CHECKPOINT_AUTHORITY_BINDING_UNREADABLE:{path.as_posix()}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"M2_CURRENT_CHECKPOINT_AUTHORITY_BINDING_NOT_OBJECT:{path.as_posix()}")
    return value


def _checkpoint_identity(
    *,
    request: Mapping[str, Any],
    request_sha256: str,
    manifest: Mapping[str, Any],
    software_revision: str,
) -> dict[str, Any]:
    """Add the complete CURRENT governance identity required for safe resume.

    The engine's compact identity remains the base. This V3 wrapper makes the
    checkpoint self-describing enough to survive chat/workflow boundaries without
    relying on memory: every required authority binding, exact GitHub execution
    identity, source-universe lineage, canonical artifact homes, and readback
    contract travel with the checkpoint.
    """

    out = _BASE_CHECKPOINT_IDENTITY(
        request=request,
        request_sha256=request_sha256,
        manifest=manifest,
        software_revision=software_revision,
    )
    lock = _load_repo_json(AUTHORITY_LOCK_PATH)
    bootstrap = _load_repo_json(AUTHORITY_BOOTSTRAP_PATH)
    lock_docs = dict(lock.get("documents") or {})
    authority_bindings: dict[str, dict[str, Any]] = {}
    for row in bootstrap.get("authority_documents_in_required_read_order") or []:
        key = str(row.get("key") or "")
        if not key:
            raise RuntimeError("M2_CURRENT_CHECKPOINT_AUTHORITY_KEY_MISSING")
        node = dict(lock_docs.get(key) or {})
        document_id = str(row.get("document_id") or node.get("document_id") or "")
        authority_revision_label = str(row.get("revision_id") or node.get("revision_id") or "")
        drive_revision_id = str(row.get("drive_revision_id") or "")
        if not document_id or not authority_revision_label or not drive_revision_id:
            raise RuntimeError(f"M2_CURRENT_CHECKPOINT_AUTHORITY_BINDING_MISSING:{key}")
        authority_bindings[key] = {
            "document_id": document_id,
            "authority_revision_label": authority_revision_label,
            "drive_revision_id": drive_revision_id,
        }

    sources = list(manifest.get("sources") or [])
    source_identity_by_name: dict[str, dict[str, Any]] = {}
    generation_ids: set[str] = set()
    implementation_versions: set[str] = set()
    for row in sources:
        name = str(row.get("source_name") or "")
        if not name:
            raise RuntimeError("M2_CURRENT_CHECKPOINT_SOURCE_NAME_MISSING")
        capability = dict(row.get("schema_source_capability") or {})
        generation = str(capability.get("generation_id") or "")
        implementation = str(capability.get("data_plane_impl_version") or "")
        if generation:
            generation_ids.add(generation)
        if implementation:
            implementation_versions.add(implementation)
        source_identity_by_name[name] = {
            "source_drive_id": row.get("source_drive_id"),
            "source_sha256": row.get("digest_sha256"),
            "eligibility": row.get("eligibility"),
            "readiness": row.get("readiness"),
            "first_date": row.get("first_date"),
            "first_time": row.get("first_time"),
            "last_date": row.get("last_date"),
            "last_time": row.get("last_time"),
            "schema_source_capability": capability,
        }

    authority_sync = dict(manifest.get("authority_sync") or {})
    out.update(
        {
            "work_id": os.environ.get("GITHUB_WORKFLOW_REF") or "LOCAL_MACHINE2_CURRENT_FULL_DEPTH_V3",
            "run_id": os.environ.get("GITHUB_RUN_ID") or "LOCAL_UNVERSIONED",
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT") or "LOCAL_UNVERSIONED",
            "repository": os.environ.get("GITHUB_REPOSITORY") or "DontAsk3010/a1-clean-orchestration",
            "branch": os.environ.get("GITHUB_REF_NAME") or "LOCAL_UNVERSIONED",
            "exact_head": software_revision,
            "workflow_identity": {
                "workflow": os.environ.get("GITHUB_WORKFLOW") or "LOCAL_UNVERSIONED",
                "workflow_ref": os.environ.get("GITHUB_WORKFLOW_REF") or "LOCAL_UNVERSIONED",
                "workflow_sha": software_revision,
            },
            "schema_versions": {
                "checkpoint": CHECKPOINT_SCHEMA,
                "scientific_object": SCIENTIFIC_OBJECT_SCHEMA,
                "date_close": DATE_CLOSE_SCHEMA,
                "owner_full_depth_extension": OWNER_FULL_DEPTH_EXTENSION_VERSION,
            },
            "tests_bound_by_exact_head": True,
            "authority_bindings": authority_bindings,
            "authority_sync_readback": {
                "schema": authority_sync.get("schema"),
                "status": authority_sync.get("status"),
                "full_authority_read_complete": authority_sync.get("full_authority_read_complete"),
                "authority_document_count": authority_sync.get("authority_document_count"),
                "repo_state_file_count": authority_sync.get("repo_state_file_count"),
                "authority_corpus_sha256": authority_sync.get("authority_corpus_sha256"),
                "bootstrap_manifest_sha256": authority_sync.get("bootstrap_manifest_sha256"),
                "active_authority_lock_sha256": authority_sync.get("active_authority_lock_sha256"),
            },
            "source_universe_generation": {
                "generation_ids": sorted(generation_ids),
                "data_plane_impl_versions": sorted(implementation_versions),
                "source_count": len(source_identity_by_name),
            },
            "source_identity_by_name": source_identity_by_name,
            "canonical_artifact_pointers": {
                "checkpoint_folder_id": MACHINE2_CHECKPOINT_FOLDER_ID,
                "semantic_output_folder_id": MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
                "current_state_folder_id": MACHINE2_CURRENT_STATE_FOLDER_ID,
            },
            "checkpoint_write_readback_state": "EXACT_BYTE_READBACK_ENFORCED_OR_WRITE_FAILS",
            "current_gaps_at_prestart": [],
            "hold_or_anomaly_at_prestart": None,
            "temporary_artifacts": [
                "RUNNER_TEMP_SOURCE_UNIVERSE_MANIFEST",
                "RUNNER_TEMP_AUTHORITY_SYNC_PROOF",
            ],
            "transport_integrity_proof": {
                "source_universe_manifest_digest": manifest.get("manifest_digest"),
                "authority_corpus_sha256": authority_sync.get("authority_corpus_sha256"),
                "manifest_status": manifest.get("status"),
            },
        }
    )
    return out


def build_current_scientific_object(*args, **kwargs):
    obj = _BASE_BUILD_CURRENT_SCIENTIFIC_OBJECT(*args, **kwargs)
    out = augment_scientific_object(obj)
    out["current_full_depth_lineage"] = LINEAGE
    out["old_v1_v2_completion_inherited"] = False
    return out


# run_trading_date resolves these helpers from engine-module globals. Bind the
# timestamp-aligned owner-full-depth builder and complete V3 checkpoint identity
# before any persisted CURRENT V3 unit.
_engine.build_current_scientific_object = build_current_scientific_object
_engine._checkpoint_identity = _checkpoint_identity

build_continuous_current_enrichment = _engine.build_continuous_current_enrichment
run_trading_date = _engine.run_trading_date
main = _engine.main


def __getattr__(name: str):
    return getattr(_engine, name)


if __name__ == "__main__":
    raise SystemExit(main())
