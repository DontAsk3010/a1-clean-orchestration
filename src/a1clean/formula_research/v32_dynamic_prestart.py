from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .source_universe_manifest import manifest_digest_is_valid, source_names_from_manifest

_REQUEST_AUTHORITY_BINDINGS = (
    ("master_handbook_document_id", "master_handbook_revision_id", "master_handbook"),
    ("formula_research_handbook_document_id", "formula_research_handbook_revision_id", "formula_research"),
    ("behavior_handbook_document_id", "behavior_handbook_revision_id", "behavior_reading"),
    ("github_automation_handbook_document_id", "github_automation_handbook_revision_id", "github_automation"),
    ("transition_bridge_document_id", "transition_bridge_revision_id", "stable_transition_bridge"),
    ("machine1_dispatch_registry_document_id", "machine1_dispatch_registry_revision_id", "machine1_dispatch_registry"),
    ("current_execution_document_id", "current_execution_revision_id", "current_execution"),
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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

    if not manifest_digest_is_valid(source_universe):
        raise RuntimeError("PRESTART_SOURCE_UNIVERSE_DIGEST_FAIL")
    names = source_names_from_manifest(source_universe, require_pass=True)
    if int(source_universe.get("source_count", -1)) != len(names):
        raise RuntimeError("PRESTART_SOURCE_UNIVERSE_COUNT_DRIFT")

    return {
        "status": "PASS",
        "request_schema": request.get("schema"),
        "request_enabled": request.get("enabled"),
        "source_universe_count": len(names),
        "source_universe_manifest_digest": source_universe.get("manifest_digest"),
        "next_source_authority": "SOURCE_UNIVERSE_MANIFEST",
        "fixed_source_count_invariant_used": False,
        "formula_stage": "CLOSED",
    }


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
