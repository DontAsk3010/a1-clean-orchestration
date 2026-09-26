from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from a1clean import canonical_recovery as cr
from a1clean.config import FROZEN_GENERATION_ID, FROZEN_IMPL_VERSION, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
from a1clean.google_drive import build_drive_api
from a1clean.source_parity import _download_bytes


ALLOWED_OPERATIONAL_TRANSITION_PATHS = {
    ".github/workflows/windows-canonical-current-recovery-chunked.yml",
    "governance/a1-clean-authority-bootstrap-current.json",
    "scripts/windows/Invoke-A1CanonicalRecoveryPrepareChunked.ps1",
    "scripts/windows/adopt_recovery_checkpoint.py",
    "scripts/windows/recovery_step.py",
    "tests/test_authority_bootstrap.py",
}


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"RECOVERY_ADOPT_GIT_FAIL:{' '.join(args)}:{proc.stderr.strip()}")
    return proc.stdout.strip()


def _compatible_checkpoint(checkpoint: dict, *, request_fp: str, evidence_fp: str) -> bool:
    return (
        checkpoint.get("schema") == cr.CHECKPOINT_SCHEMA
        and checkpoint.get("request_fingerprint") == request_fp
        and checkpoint.get("evidence_fingerprint") == evidence_fp
        and checkpoint.get("generation_id") == FROZEN_GENERATION_ID
        and checkpoint.get("data_plane_impl_version") == FROZEN_IMPL_VERSION
    )


def _find_compatible_run(api, *, request_fp: str, evidence_fp: str):
    request_suffix = f"_{request_fp[:12]}"
    rows = sorted(
        [
            x
            for x in cr._list_children(api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID)
            if x.get("mimeType") == cr.FOLDER_MIME
            and str(x.get("name", "")).startswith("CANONICAL_CURRENT_RECOVERY_PREPARE_")
            and str(x.get("name", "")).endswith(request_suffix)
        ],
        key=lambda x: str(x.get("name")),
        reverse=True,
    )
    for folder in rows:
        cps = sorted(
            [
                x
                for x in cr._list_children(api, folder["id"])
                if x.get("mimeType") != cr.FOLDER_MIME
                and str(x.get("name", "")).startswith("CHECKPOINT_")
            ],
            key=lambda x: str(x.get("name")),
        )
        if not cps:
            continue
        checkpoint = cr._download_json(api, cps[-1]["id"])
        if _compatible_checkpoint(checkpoint, request_fp=request_fp, evidence_fp=evidence_fp):
            return folder, checkpoint
    return None, None


def _file_map(api, folder_id: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for item in cr._list_children(api, folder_id):
        if item.get("mimeType") == cr.FOLDER_MIME:
            raise RuntimeError(f"RECOVERY_ADOPT_UNEXPECTED_NESTED_FOLDER:{folder_id}:{item.get('name')}")
        name = str(item.get("name") or "")
        if not name or name in rows:
            raise RuntimeError(f"RECOVERY_ADOPT_DUPLICATE_OR_EMPTY_NAME:{folder_id}:{name}")
        rows[name] = {
            "id": str(item.get("id") or ""),
            "size": int(item.get("size") or -1),
            "md5": str(item.get("md5Checksum") or "").lower(),
        }
    return rows


def _normalized_hash_map(rows: dict[str, dict]) -> dict[str, dict]:
    return {name: {"size": int(meta["size"]), "md5": str(meta["md5"]).lower()} for name, meta in rows.items()}


def _event_tree_fingerprint(api, folder_id: str) -> str:
    items = sorted(
        [x for x in cr._list_children(api, folder_id) if x.get("mimeType") != cr.FOLDER_MIME],
        key=lambda x: str(x.get("name")),
    )
    if not items:
        raise RuntimeError("RECOVERY_ADOPT_EVENT_CONTRACT_EMPTY")
    rows = []
    for item in items:
        body = _download_bytes(api, item["id"])
        rows.append(
            {
                "relative_path": str(item.get("name") or ""),
                "size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return cr._json_fingerprint(rows)


def _validate_completed_source(api, *, row: dict, expected: dict, expected_index: int, checkpoint_event_fp: str | None) -> dict:
    drive_id = expected["drive_id"]
    stable = expected["stable_source"]
    expected_sha = str(stable.get("source_sha256") or "")
    checks = {
        "pass": row.get("pass") is True,
        "source_index": int(row.get("source_index") or -1) == expected_index,
        "source_name": str(row.get("source_name") or "") == expected["name"],
        "source_drive_id": str(row.get("source_drive_id") or "") == drive_id,
        "source_sha256": str(row.get("source_sha256") or "") == expected_sha,
        "physical_file_count": int(row.get("physical_file_count") or -1) == len(expected["physical"]),
        "semantic_file_count": int(row.get("semantic_file_count") or -1) == len(expected["semantic"]),
        "historical_source_report_id": str(row.get("historical_source_report_id") or "") == expected["historical_source_report_id"],
        "event_fp_checkpoint": checkpoint_event_fp is None
        or str(row.get("event_contract_tree_fingerprint") or "") == checkpoint_event_fp,
    }
    if not all(checks.values()):
        raise RuntimeError(f"RECOVERY_ADOPT_COMPLETED_IDENTITY_FAIL:{expected['name']}:{checks}")

    staging = row.get("staging") or {}
    if staging.get("pass") is not True:
        raise RuntimeError(f"RECOVERY_ADOPT_STAGING_NOT_PASS:{expected['name']}")
    source_folder_id = str(staging.get("folder_id") or "")
    logical = dict(staging.get("logical_folder_ids") or {})
    required_logical = {
        "00_MANIFESTS",
        "01_ACCESS_SHARDS",
        "02_SEMANTIC_BUNDLES",
        "03_MARKET_DAY_INDEX",
        "04_SEMANTIC_EVENT_CONTRACT",
    }
    if set(logical) != required_logical or not source_folder_id:
        raise RuntimeError(f"RECOVERY_ADOPT_LOGICAL_FOLDER_SET_FAIL:{expected['name']}")

    source_children = {
        str(x.get("name")): str(x.get("id"))
        for x in cr._list_children(api, source_folder_id)
        if x.get("mimeType") == cr.FOLDER_MIME
    }
    for name, folder_id in logical.items():
        if source_children.get(name) != str(folder_id):
            raise RuntimeError(f"RECOVERY_ADOPT_LOGICAL_FOLDER_PARENT_FAIL:{expected['name']}:{name}")

    physical = _file_map(api, logical["01_ACCESS_SHARDS"])
    semantic = _file_map(api, logical["02_SEMANTIC_BUNDLES"])
    if _normalized_hash_map(physical) != expected["physical"]:
        raise RuntimeError(f"RECOVERY_ADOPT_PHYSICAL_READBACK_FAIL:{expected['name']}")
    if _normalized_hash_map(semantic) != expected["semantic"]:
        raise RuntimeError(f"RECOVERY_ADOPT_SEMANTIC_READBACK_FAIL:{expected['name']}")

    stem = Path(expected["name"]).stem
    manifests = _file_map(api, logical["00_MANIFESTS"])
    manifest_names = {
        f"{stem}__DATA_PLANE_MANIFEST.json",
        f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json",
    }
    if set(manifests) != manifest_names:
        raise RuntimeError(f"RECOVERY_ADOPT_MANIFEST_FILESET_FAIL:{expected['name']}")
    data_manifest = cr._download_json(api, manifests[f"{stem}__DATA_PLANE_MANIFEST.json"]["id"])
    if cr._stable_source(data_manifest) != stable:
        raise RuntimeError(f"RECOVERY_ADOPT_STABLE_MANIFEST_FAIL:{expected['name']}")
    semantic_manifest = cr._download_json(api, manifests[f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"]["id"])
    if semantic_manifest != cr._download_json(api, expected["semantic_manifest_evidence_id"]):
        raise RuntimeError(f"RECOVERY_ADOPT_SEMANTIC_MANIFEST_FAIL:{expected['name']}")

    market = _file_map(api, logical["03_MARKET_DAY_INDEX"])
    market_name = f"{stem}__MARKET_DAY_INDEX.json"
    if set(market) != {market_name}:
        raise RuntimeError(f"RECOVERY_ADOPT_MARKET_FILESET_FAIL:{expected['name']}")
    if cr._download_json(api, market[market_name]["id"]) != cr._download_json(api, expected["market_index_evidence_id"]):
        raise RuntimeError(f"RECOVERY_ADOPT_MARKET_INDEX_FAIL:{expected['name']}")

    event_fp = _event_tree_fingerprint(api, logical["04_SEMANTIC_EVENT_CONTRACT"])
    if event_fp != str(row.get("event_contract_tree_fingerprint") or ""):
        raise RuntimeError(f"RECOVERY_ADOPT_EVENT_FINGERPRINT_FAIL:{expected['name']}")

    return {
        "source_name": expected["name"],
        "source_drive_id": drive_id,
        "physical_files": len(physical),
        "semantic_files": len(semantic),
        "event_contract_tree_fingerprint": event_fp,
        "readback": "PASS_EXACT_STAGED_ARTIFACTS",
    }


def main() -> int:
    request = cr._load_request(cr.REQUEST_PATH)
    request_fp = cr._json_fingerprint(request)
    api = build_drive_api(read_write=True)
    evidence = cr._load_full_shadow_evidence(api, request["full_shadow_evidence_folder_id"])
    folder, checkpoint = _find_compatible_run(
        api,
        request_fp=request_fp,
        evidence_fp=evidence["evidence_fingerprint"],
    )
    if folder is None or checkpoint is None:
        raise RuntimeError("RECOVERY_ADOPT_COMPATIBLE_RUN_NOT_FOUND")
    if checkpoint.get("canonical_write_performed") is not False or checkpoint.get("raw_write_performed") is not False:
        raise RuntimeError("RECOVERY_ADOPT_FORBIDDEN_MUTATION_FLAG")

    current_sha = str(os.environ.get("GITHUB_SHA") or "").strip()
    if not current_sha:
        raise RuntimeError("RECOVERY_ADOPT_CURRENT_GITHUB_SHA_MISSING")
    head_sha = _git("rev-parse", "HEAD")
    if head_sha != current_sha:
        raise RuntimeError(f"RECOVERY_ADOPT_HEAD_SHA_MISMATCH:{head_sha}:{current_sha}")

    prior_sha = str(checkpoint.get("github_sha") or "")
    completed = dict(checkpoint.get("completed_sources") or {})
    if prior_sha == current_sha:
        result = {
            "pass": True,
            "status": "PASS_ALREADY_CURRENT_SHA",
            "run_folder_id": folder["id"],
            "github_sha": current_sha,
            "carried_completed_source_count": len(completed),
            "checkpoint_mutation_performed": False,
        }
        print("A1_RECOVERY_CHECKPOINT_ADOPTION_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
        return 0

    if not prior_sha:
        raise RuntimeError("RECOVERY_ADOPT_PRIOR_GITHUB_SHA_MISSING")
    try:
        _git("cat-file", "-e", f"{prior_sha}^{{commit}}")
    except RuntimeError:
        _git("fetch", "--no-tags", "--depth=1", "origin", prior_sha)
    changed_paths = [p for p in _git("diff", "--name-only", f"{prior_sha}..{current_sha}").splitlines() if p]
    unexpected = sorted(set(changed_paths) - ALLOWED_OPERATIONAL_TRANSITION_PATHS)
    if unexpected:
        raise RuntimeError(f"RECOVERY_ADOPT_UNEXPECTED_SOFTWARE_CHANGE:{unexpected}")

    expected_by_id = {row["drive_id"]: (idx, row) for idx, row in enumerate(evidence["sources"], start=1)}
    if not completed:
        validation_rows = []
    else:
        unknown = sorted(set(completed) - set(expected_by_id))
        if unknown:
            raise RuntimeError(f"RECOVERY_ADOPT_UNKNOWN_COMPLETED_SOURCE:{unknown}")
        checkpoint_event_fp = checkpoint.get("event_contract_tree_fingerprint")
        validation_rows = []
        for drive_id, completed_row in sorted(completed.items(), key=lambda item: expected_by_id[item[0]][0]):
            expected_index, expected = expected_by_id[drive_id]
            validation_rows.append(
                _validate_completed_source(
                    api,
                    row=completed_row,
                    expected=expected,
                    expected_index=expected_index,
                    checkpoint_event_fp=checkpoint_event_fp,
                )
            )

    authority_path = Path("governance/a1-clean-authority-bootstrap-current.json")
    if not authority_path.is_file():
        raise RuntimeError("RECOVERY_ADOPT_AUTHORITY_BOOTSTRAP_MISSING")
    authority_sha256 = hashlib.sha256(authority_path.read_bytes()).hexdigest()

    checkpoint = dict(checkpoint)
    lineage = list(checkpoint.get("software_lineage") or [])
    lineage.append(
        {
            "from_github_sha": prior_sha,
            "to_github_sha": current_sha,
            "changed_paths": changed_paths,
            "allowlist_validation": "PASS_OPERATIONAL_WRAPPER_ONLY_NO_RECOVERY_ENGINE_CORE_CHANGE",
            "completed_source_carry_validation": validation_rows,
            "authority_bootstrap_sha256": authority_sha256,
            "at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    checkpoint["software_lineage"] = lineage
    checkpoint["resumed_from_github_sha"] = prior_sha
    checkpoint["github_sha"] = current_sha
    checkpoint["authority_bootstrap_sha256"] = authority_sha256
    checkpoint["durable_completed_source_reuse"] = "PASS_EXACT_IDENTITY_AND_STAGED_READBACK"
    checkpoint["execution_decision"] = "CONTINUE_RECOVERY_PREPARE_ONLY_FROM_EXACT_NEXT_SOURCE_NO_RESTART_NO_CANONICAL_WRITE"
    checkpoint["status"] = "IN_PROGRESS"
    checkpoint.pop("hold", None)
    checkpoint["sequence"] = int(checkpoint.get("sequence") or 0) + 1
    cr._checkpoint_upload(api, checkpoint["run_folder_id"], checkpoint)

    result = {
        "pass": True,
        "status": "PASS_CHECKPOINT_SHA_ADOPTED_WITH_EXACT_READBACK",
        "run_folder_id": checkpoint["run_folder_id"],
        "prior_github_sha": prior_sha,
        "github_sha": current_sha,
        "changed_paths": changed_paths,
        "carried_completed_source_count": len(completed),
        "next_exact_resume_source": checkpoint.get("next_exact_resume_source"),
        "authority_bootstrap_sha256": authority_sha256,
        "canonical_write_performed": False,
        "raw_write_performed": False,
        "checkpoint_mutation_performed": True,
    }
    print("A1_RECOVERY_CHECKPOINT_ADOPTION_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
