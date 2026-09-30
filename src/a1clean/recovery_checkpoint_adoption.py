from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from a1clean import canonical_recovery as cr
from a1clean.config import FROZEN_GENERATION_ID, FROZEN_IMPL_VERSION, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
from a1clean.delta_artifacts import upload_json_payload
from a1clean.google_drive import build_drive_api
from a1clean.source_parity import _download_bytes
from a1clean.source_preflight import run_source_preflight


REQUEST_PATH = "canonical-current-recovery-requests/current.json"
TRIGGER_ONLY_REQUEST_KEYS = {"trigger_revision"}
ALLOWED_OPERATIONAL_TRANSITION_PATHS = {
    ".github/workflows/windows-canonical-current-recovery-chunked.yml",
    "canonical-current-recovery-requests/current.json",
    "canonical-current-recovery-requests/recovery-prepare-blocker-current.json",
    "governance/a1-clean-active-authority-lock.json",
    "governance/a1-clean-authority-bootstrap-current.json",
    "scripts/windows/Invoke-A1CanonicalRecoveryPrepareChunked.ps1",
    "scripts/windows/adopt_recovery_checkpoint.py",
    "scripts/windows/recovery_step.py",
    "src/a1clean/recovery_checkpoint_adoption.py",
    "tests/test_authority_bootstrap.py",
    "v32-full-observation-behavior-requests/current.json",
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


def _git_json(sha: str, path: str) -> dict:
    try:
        raw = _git("show", f"{sha}:{path}")
    except RuntimeError:
        _git("fetch", "--no-tags", "--depth=1", "origin", sha)
        raw = _git("show", f"{sha}:{path}")
    return json.loads(raw)


def _strip_trigger_only_keys(value: dict) -> dict:
    return {k: v for k, v in value.items() if k not in TRIGGER_ONLY_REQUEST_KEYS}


def _request_transition(checkpoint: dict, current_request: dict, current_fp: str) -> dict | None:
    checkpoint_fp = str(checkpoint.get("request_fingerprint") or "")
    if checkpoint_fp == current_fp:
        return {
            "status": "PASS_EXACT_CURRENT_REQUEST_FINGERPRINT",
            "prior_trigger_revision": current_request.get("trigger_revision"),
            "current_trigger_revision": current_request.get("trigger_revision"),
        }
    prior_sha = str(checkpoint.get("github_sha") or "")
    if not prior_sha:
        return None
    prior_request = _git_json(prior_sha, REQUEST_PATH)
    if cr._json_fingerprint(prior_request) != checkpoint_fp:
        return None
    if _strip_trigger_only_keys(prior_request) != _strip_trigger_only_keys(current_request):
        return None
    return {
        "status": "PASS_TRIGGER_REVISION_ONLY_REQUEST_TRANSITION",
        "prior_trigger_revision": prior_request.get("trigger_revision"),
        "current_trigger_revision": current_request.get("trigger_revision"),
        "prior_request_fingerprint": checkpoint_fp,
        "current_request_fingerprint": current_fp,
    }


def _checkpoint_base_compatible(checkpoint: dict, *, evidence_fp: str) -> bool:
    return (
        checkpoint.get("schema") == cr.CHECKPOINT_SCHEMA
        and checkpoint.get("evidence_fingerprint") == evidence_fp
        and checkpoint.get("generation_id") == FROZEN_GENERATION_ID
        and checkpoint.get("data_plane_impl_version") == FROZEN_IMPL_VERSION
    )


def _find_compatible_run(api, *, current_request: dict, request_fp: str, evidence_fp: str):
    candidates = []
    for folder in cr._list_children(api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID):
        if folder.get("mimeType") != cr.FOLDER_MIME:
            continue
        if not str(folder.get("name", "")).startswith("CANONICAL_CURRENT_RECOVERY_PREPARE_"):
            continue
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
        if not _checkpoint_base_compatible(checkpoint, evidence_fp=evidence_fp):
            continue
        transition = _request_transition(checkpoint, current_request, request_fp)
        if transition is None:
            continue
        completed_count = len(dict(checkpoint.get("completed_sources") or {}))
        sequence = int(checkpoint.get("sequence") or 0)
        candidates.append((completed_count, sequence, str(folder.get("name") or ""), folder, checkpoint, transition))
    if not candidates:
        return None, None, None
    _, _, _, folder, checkpoint, transition = sorted(candidates, reverse=True, key=lambda r: (r[0], r[1], r[2]))[0]
    return folder, checkpoint, transition


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
            "name": name,
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
    required_logical = set(cr.SOURCE_LOGICAL_FOLDERS)
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


def _candidate_folder_state(api, candidate: dict) -> tuple[dict[str, str], int] | None:
    children = cr._list_children(api, candidate["id"])
    folders = [x for x in children if x.get("mimeType") == cr.FOLDER_MIME]
    names = [str(x.get("name") or "") for x in folders]
    if len(names) != len(set(names)):
        return None
    if set(names) != set(cr.SOURCE_LOGICAL_FOLDERS):
        return None
    logical_ids = {str(x["name"]): str(x["id"]) for x in folders}
    file_count = sum(len(_file_map(api, folder_id)) for folder_id in logical_ids.values())
    return logical_ids, file_count


def _find_or_create_candidate(api, run_folder_id: str) -> tuple[str, dict[str, str], list[str], bool]:
    viable = []
    all_candidates = [
        x
        for x in cr._list_children(api, run_folder_id)
        if x.get("mimeType") == cr.FOLDER_MIME and str(x.get("name") or "").startswith("CANDIDATE_CURRENT_")
    ]
    for candidate in all_candidates:
        state = _candidate_folder_state(api, candidate)
        if state is not None:
            logical_ids, file_count = state
            viable.append((file_count, str(candidate.get("name") or ""), candidate, logical_ids))
    if viable:
        _, _, chosen, logical_ids = sorted(viable, reverse=True, key=lambda r: (r[0], r[1]))[0]
        ignored = [str(x.get("id")) for x in all_candidates if str(x.get("id")) != str(chosen.get("id"))]
        return str(chosen["id"]), logical_ids, ignored, True

    candidate_id = cr._create_folder(api, parent_id=run_folder_id, name=f"CANDIDATE_CURRENT_{cr._utc_stamp()}")
    logical_ids = {
        logical: cr._create_folder(api, parent_id=candidate_id, name=logical)
        for logical in cr.SOURCE_LOGICAL_FOLDERS
    }
    return candidate_id, logical_ids, [str(x.get("id")) for x in all_candidates], False


def _source_meta_map(api, folder_id: str) -> dict[str, dict]:
    return _file_map(api, folder_id)


def _merge_expected(target: dict[str, dict], incoming: dict[str, dict], *, logical: str, origin: str) -> None:
    for name, meta in incoming.items():
        if name in target:
            old = target[name]
            if int(old["size"]) != int(meta["size"]) or str(old["md5"]).lower() != str(meta["md5"]).lower():
                raise RuntimeError(f"RECOVERY_ADOPT_EXPECTED_NAME_COLLISION:{logical}:{name}:{origin}")
            raise RuntimeError(f"RECOVERY_ADOPT_EXPECTED_DUPLICATE_NAME:{logical}:{name}:{origin}")
        target[name] = meta


def _ensure_target_file(api, *, source: dict, target_folder_id: str, name: str, max_attempts: int = 5) -> tuple[dict, bool]:
    expected_size = int(source.get("size") or -1)
    expected_md5 = str(source.get("md5") or "").lower()
    if expected_size < 0 or not expected_md5:
        raise RuntimeError(f"RECOVERY_ADOPT_COPY_SOURCE_METADATA_MISSING:{name}")

    for attempt in range(1, max_attempts + 1):
        existing = _file_map(api, target_folder_id)
        if name in existing:
            row = existing[name]
            if int(row["size"]) != expected_size or str(row["md5"]).lower() != expected_md5:
                raise RuntimeError(f"RECOVERY_ADOPT_EXISTING_TARGET_MISMATCH:{name}")
            return row, True
        try:
            api.files().copy(
                fileId=source["id"],
                body={"name": name, "parents": [target_folder_id]},
                fields="id,name,size,md5Checksum,parents",
                supportsAllDrives=True,
            ).execute()
        except Exception as exc:
            after = _file_map(api, target_folder_id)
            if name in after:
                row = after[name]
                if int(row["size"]) == expected_size and str(row["md5"]).lower() == expected_md5:
                    return row, True
                raise RuntimeError(f"RECOVERY_ADOPT_POST_TIMEOUT_TARGET_MISMATCH:{name}") from exc
            if attempt >= max_attempts:
                raise RuntimeError(f"RECOVERY_ADOPT_DRIVE_COPY_RETRY_EXHAUSTED:{name}:{type(exc).__name__}:{exc}") from exc
            time.sleep(min(2 ** attempt, 16))
            continue

        verified = _file_map(api, target_folder_id)
        if name not in verified:
            if attempt >= max_attempts:
                raise RuntimeError(f"RECOVERY_ADOPT_COPY_NOT_VISIBLE_AFTER_SUCCESS:{name}")
            time.sleep(min(2 ** attempt, 16))
            continue
        row = verified[name]
        if int(row["size"]) != expected_size or str(row["md5"]).lower() != expected_md5:
            raise RuntimeError(f"RECOVERY_ADOPT_COPIED_TARGET_MISMATCH:{name}")
        return row, False
    raise RuntimeError(f"RECOVERY_ADOPT_COPY_UNREACHABLE:{name}")


def _resume_candidate_assembly(api, *, run_folder_id: str, completed: dict[str, dict], evidence: list[dict], controls_id: str) -> dict:
    candidate_id, targets, ignored_candidates, resumed_candidate = _find_or_create_candidate(api, run_folder_id)
    expected: dict[str, dict[str, dict]] = {logical: {} for logical in cr.SOURCE_LOGICAL_FOLDERS}

    for source in evidence:
        staged = completed[source["drive_id"]]["staging"]["logical_folder_ids"]
        for logical in cr.SOURCE_LOGICAL_FOLDERS[:4]:
            _merge_expected(expected[logical], _source_meta_map(api, staged[logical]), logical=logical, origin=source["name"])

    first_staged = completed[evidence[0]["drive_id"]]["staging"]["logical_folder_ids"]
    _merge_expected(
        expected["04_SEMANTIC_EVENT_CONTRACT"],
        _source_meta_map(api, first_staged["04_SEMANTIC_EVENT_CONTRACT"]),
        logical="04_SEMANTIC_EVENT_CONTRACT",
        origin=evidence[0]["name"],
    )

    controls = _source_meta_map(api, controls_id)
    missing_controls = sorted(set(cr.DATA_PLANE_CONTROL_FILES) - set(controls))
    if missing_controls:
        raise RuntimeError(f"RECOVERY_ADOPT_COMMITTED_CONTROL_BUNDLE_INCOMPLETE:{missing_controls}")
    control_subset = {name: controls[name] for name in cr.DATA_PLANE_CONTROL_FILES}
    _merge_expected(expected["00_MANIFESTS"], control_subset, logical="00_MANIFESTS", origin="CONTROL_BUNDLE")

    copied_new = 0
    reused_existing = 0
    for logical in cr.SOURCE_LOGICAL_FOLDERS:
        for name, source_meta in sorted(expected[logical].items()):
            _, reused = _ensure_target_file(api, source=source_meta, target_folder_id=targets[logical], name=name)
            if reused:
                reused_existing += 1
            else:
                copied_new += 1

    readback = {}
    checks = {}
    for logical in cr.SOURCE_LOGICAL_FOLDERS:
        observed = _file_map(api, targets[logical])
        expected_map = expected[logical]
        exact_names = set(observed) == set(expected_map)
        exact_hashes = exact_names and _normalized_hash_map(observed) == _normalized_hash_map(expected_map)
        checks[f"{logical}_exact_names"] = exact_names
        checks[f"{logical}_exact_size_md5"] = exact_hashes
        readback[logical] = {
            "file_count": len(observed),
            "names_fingerprint": cr._json_fingerprint(sorted(observed)),
            "exact_names": exact_names,
            "exact_size_md5": exact_hashes,
        }
    if not all(checks.values()):
        raise RuntimeError(f"RECOVERY_ADOPT_CANDIDATE_EXACT_READBACK_HOLD:{checks}")

    return {
        "pass": True,
        "candidate_folder_id": candidate_id,
        "candidate_folder_role": "STAGING_ONLY_NOT_CANONICAL_CURRENT",
        "logical_folder_ids": targets,
        "resumed_existing_candidate": resumed_candidate,
        "ignored_orphan_candidate_folder_ids": ignored_candidates,
        "copy_count": copied_new + reused_existing,
        "new_copy_count": copied_new,
        "reused_verified_copy_count": reused_existing,
        "readback": readback,
        "checks": checks,
    }


def _rename_run_for_current_request(api, folder: dict, request_fp: str) -> str:
    current_name = str(folder.get("name") or "")
    desired_suffix = f"_{request_fp[:12]}"
    if current_name.endswith(desired_suffix):
        return current_name
    if "_" not in current_name:
        raise RuntimeError("RECOVERY_ADOPT_RUN_FOLDER_NAME_INVALID")
    desired_name = current_name.rsplit("_", 1)[0] + desired_suffix
    siblings = [
        x for x in cr._list_children(api, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID)
        if str(x.get("name") or "") == desired_name and str(x.get("id")) != str(folder.get("id"))
    ]
    if siblings:
        raise RuntimeError(f"RECOVERY_ADOPT_RUN_RENAME_COLLISION:{desired_name}")
    result = api.files().update(
        fileId=folder["id"],
        body={"name": desired_name},
        fields="id,name,parents",
        supportsAllDrives=True,
    ).execute()
    if str(result.get("name") or "") != desired_name:
        raise RuntimeError("RECOVERY_ADOPT_RUN_RENAME_READBACK_FAIL")
    folder["name"] = desired_name
    return desired_name


def _persist_final_if_absent(api, *, run_folder_id: str, final: dict) -> None:
    matches = [
        x for x in cr._list_children(api, run_folder_id)
        if x.get("mimeType") != cr.FOLDER_MIME and str(x.get("name") or "") == "RECOVERY_PREPARE_FINAL.json"
    ]
    if len(matches) > 1:
        raise RuntimeError("RECOVERY_ADOPT_DUPLICATE_FINAL_REPORT")
    if matches:
        existing = cr._download_json(api, matches[0]["id"])
        if existing != final:
            raise RuntimeError("RECOVERY_ADOPT_EXISTING_FINAL_REPORT_MISMATCH")
        return
    uploaded = upload_json_payload(api, parent_id=run_folder_id, name="RECOVERY_PREPARE_FINAL.json", payload=final)
    if uploaded.get("pass") is not True:
        raise RuntimeError("RECOVERY_ADOPT_FINAL_REPORT_UPLOAD_FAILED")


def main() -> int:
    request = cr._load_request(cr.REQUEST_PATH)
    request_fp = cr._json_fingerprint(request)
    reader_api = build_drive_api(read_write=False)
    api = build_drive_api(read_write=True)
    evidence = cr._load_full_shadow_evidence(reader_api, request["full_shadow_evidence_folder_id"])

    folder, checkpoint, request_transition = _find_compatible_run(
        api,
        current_request=request,
        request_fp=request_fp,
        evidence_fp=evidence["evidence_fingerprint"],
    )
    if folder is None or checkpoint is None or request_transition is None:
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

    completed = dict(checkpoint.get("completed_sources") or {})
    expected_by_id = {row["drive_id"]: (idx, row) for idx, row in enumerate(evidence["sources"], start=1)}
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
            "allowlist_validation": "PASS_OPERATIONAL_GOVERNANCE_AND_ADOPTION_ONLY_NO_SOURCE_REGENERATION_CORE_CHANGE",
            "request_transition_validation": request_transition,
            "completed_source_carry_validation": validation_rows,
            "authority_bootstrap_sha256": authority_sha256,
            "at_utc": datetime.now(timezone.utc).isoformat(),
        }
    )
    checkpoint["software_lineage"] = lineage
    checkpoint["resumed_from_github_sha"] = prior_sha
    checkpoint["github_sha"] = current_sha
    checkpoint["request_fingerprint"] = request_fp
    checkpoint["request_transition_validation"] = request_transition
    checkpoint["authority_bootstrap_sha256"] = authority_sha256
    checkpoint["durable_completed_source_reuse"] = "PASS_EXACT_IDENTITY_AND_STAGED_READBACK"
    checkpoint["execution_decision"] = "CONTINUE_RECOVERY_PREPARE_FROM_DURABLE_COMPLETED_SOURCES_NO_RESTART_NO_CANONICAL_WRITE"
    checkpoint["status"] = "IN_PROGRESS"
    checkpoint.pop("hold", None)
    checkpoint["sequence"] = int(checkpoint.get("sequence") or 0) + 1
    cr._checkpoint_upload(api, checkpoint["run_folder_id"], checkpoint)
    _rename_run_for_current_request(api, folder, request_fp)

    all_sources_complete = len(completed) == len(evidence["sources"]) and all(
        completed.get(row["drive_id"], {}).get("pass") is True for row in evidence["sources"]
    )

    if all_sources_complete:
        try:
            assembly = _resume_candidate_assembly(
                api,
                run_folder_id=checkpoint["run_folder_id"],
                completed=completed,
                evidence=evidence["sources"],
                controls_id=request["committed_control_bundle_folder_id"],
            )
            preflight = run_source_preflight()
            if preflight.get("pass") is not True:
                raise RuntimeError("RECOVERY_ADOPT_RAW_SOURCE_PREFLIGHT_HOLD")
            _, extras = cr._validate_raw_sources(preflight, evidence)
            missing_reader = cr._assert_expected_current_missing(reader_api, request["expected_missing_current_folder_id"])
            missing_writer = cr._assert_expected_current_missing(api, request["expected_missing_current_folder_id"])
            final = {
                "schema": cr.FINAL_SCHEMA,
                "pass": True,
                "status": "PASS_PREPARED_STAGING_ONLY",
                "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
                "run_folder_id": checkpoint["run_folder_id"],
                "resumed_existing_run": True,
                "github_sha": current_sha,
                "request_fingerprint": request_fp,
                "evidence_fingerprint": evidence["evidence_fingerprint"],
                "missing_current_reader": missing_reader,
                "missing_current_writer": missing_writer,
                "recovered_source_count": len(completed),
                "baseline_source_count_is_snapshot_not_invariant": True,
                "current_raw_extra_sources_not_promoted_by_recovery": [r.get("name") for r in extras],
                "source_body_validation": "PHYSICAL_AND_SEMANTIC_EXACT_NAME_SIZE_MD5_AGAINST_PRIOR_PASS_EVIDENCE; SEMANTIC_MANIFEST_AND_MARKET_INDEX_EXACT_JSON; SOURCE_MANIFEST_STABLE_FIELDS_EXACT",
                "event_contract_validation": "REGENERATED_BY_FROZEN_ENGINE_AND_IDENTICAL_ACROSS_ALL_RECOVERED_SOURCES; HISTORICAL_CURRENT_BYTE_SNAPSHOT_NOT_AVAILABLE",
                "controls_validation": "SERVER_SIDE_COPY_OF_EXACT_COMMITTED_DATA_PLANE_CONTROL_BUNDLE_FROM_LAST_GOVERNED_PROMOTION_SHADOW",
                "event_contract_tree_fingerprint": checkpoint.get("event_contract_tree_fingerprint"),
                "assembly": assembly,
                "canonical_current_expected_old_id": request["expected_missing_current_folder_id"],
                "canonical_write_performed": False,
                "raw_write_performed": False,
                "promotion_authorized": False,
                "next_gate": "SEPARATE_GOVERNED_PROMOTION_AND_POST_PROMOTION_READBACK_REQUIRED",
                "adoption_finalizer": "PASS_RESUMED_EXISTING_CANDIDATE_WITH_EXACT_SIZE_MD5_READBACK",
            }
            _persist_final_if_absent(api, run_folder_id=checkpoint["run_folder_id"], final=final)
            checkpoint["status"] = "PASS_PREPARED"
            checkpoint["next_exact_resume_source"] = None
            checkpoint["completed_sources"] = completed
            checkpoint["candidate_current_folder_id"] = assembly["candidate_folder_id"]
            checkpoint["canonical_write_performed"] = False
            checkpoint["raw_write_performed"] = False
            checkpoint["finalization_recovery"] = {
                "status": "PASS",
                "reason": "RESUMED_AFTER_DRIVE_COPY_TIMEOUT_WITH_IDEMPOTENT_EXACT_READBACK",
                "assembly": assembly,
                "at_utc": datetime.now(timezone.utc).isoformat(),
            }
            checkpoint["sequence"] = int(checkpoint.get("sequence") or 0) + 1
            cr._checkpoint_upload(api, checkpoint["run_folder_id"], checkpoint)
            result = {
                "pass": True,
                "status": "PASS_CHECKPOINT_ADOPTED_AND_FINALIZED_FROM_DURABLE_18_SOURCE_STATE",
                "run_folder_id": checkpoint["run_folder_id"],
                "prior_github_sha": prior_sha,
                "github_sha": current_sha,
                "changed_paths": changed_paths,
                "carried_completed_source_count": len(completed),
                "next_exact_resume_source": None,
                "candidate_folder_id": assembly["candidate_folder_id"],
                "authority_bootstrap_sha256": authority_sha256,
                "canonical_write_performed": False,
                "raw_write_performed": False,
                "checkpoint_mutation_performed": True,
            }
            print("A1_RECOVERY_CHECKPOINT_ADOPTION_JSON=" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
            return 0
        except Exception as exc:
            checkpoint["status"] = "HOLD_FINALIZATION"
            checkpoint["completed_sources"] = completed
            checkpoint["hold"] = {
                "stage": "FINALIZATION",
                "reason": f"{type(exc).__name__}: {exc}",
                "at_utc": datetime.now(timezone.utc).isoformat(),
            }
            checkpoint["sequence"] = int(checkpoint.get("sequence") or 0) + 1
            cr._checkpoint_upload(api, checkpoint["run_folder_id"], checkpoint)
            raise

    result = {
        "pass": True,
        "status": "PASS_CHECKPOINT_SHA_REQUEST_ADOPTED_WITH_EXACT_READBACK",
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
