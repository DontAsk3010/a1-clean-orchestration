from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from . import canonical_recovery as cr
from .config import FROZEN_CURRENT_FOLDER_DRIVE_ID, FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
from .google_drive import build_drive_api


REQUEST_SCHEMA = "A1_CANONICAL_CURRENT_RECOVERY_PROMOTION_PREPARE_REQUEST_V1"
RESULT_SCHEMA = "A1_CANONICAL_CURRENT_RECOVERY_PROMOTION_PREPARE_RESULT_V1"
REQUEST_PATH = Path("canonical-current-recovery-requests/promotion-prepare-current.json")
CANONICAL_ROOT_NAME = "UNIVERSAL_BEHAVIOR_DATA_PLANE_CURRENT"
CANONICAL_PARENT_NAME = "01_RUNTIME_INGEST"
EXPECTED_LOGICAL = cr.SOURCE_LOGICAL_FOLDERS


def _json_fp(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_request(path: Path = REQUEST_PATH) -> dict:
    req = json.loads(path.read_text(encoding="utf-8"))
    exact = {
        "schema": REQUEST_SCHEMA,
        "enabled": True,
        "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
        "expected_missing_current_folder_id": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "parity_staging_folder_id": FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        "canonical_root_name": CANONICAL_ROOT_NAME,
        "canonical_parent_folder_name": CANONICAL_PARENT_NAME,
        "canonical_promotion_allowed": False,
        "canonical_current_recovery_commit_authorized": False,
        "raw_write_allowed": False,
        "heavy_behavior_research_allowed": False,
    }
    for key, expected in exact.items():
        if req.get(key) != expected:
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_REQUEST_LOCK_MISMATCH:{key}")
    for key in (
        "expected_recovery_github_sha",
        "run_folder_id",
        "final_report_file_id",
        "checkpoint_file_id",
        "candidate_folder_id",
        "canonical_parent_folder_id",
    ):
        if not str(req.get(key) or "").strip():
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_REQUEST_MISSING:{key}")
    return req


def _meta(api, file_id: str) -> dict:
    return api.files().get(
        fileId=file_id,
        fields="id,name,mimeType,parents,trashed,createdTime,modifiedTime",
        supportsAllDrives=True,
    ).execute()


def _file_rows(api, folder_id: str) -> list[dict]:
    rows = []
    for item in cr._list_children(api, folder_id):
        if item.get("mimeType") == cr.FOLDER_MIME:
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_UNEXPECTED_NESTED_FOLDER:{folder_id}:{item.get('name')}")
        name = str(item.get("name") or "")
        md5 = str(item.get("md5Checksum") or "").lower()
        size_raw = item.get("size")
        if not name or not md5 or size_raw is None:
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_FILE_IDENTITY_INCOMPLETE:{folder_id}:{name}")
        rows.append({
            "id": str(item.get("id") or ""),
            "name": name,
            "size": int(size_raw),
            "md5": md5,
        })
    names = [r["name"] for r in rows]
    if len(names) != len(set(names)):
        raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_DUPLICATE_NAMES:{folder_id}")
    return sorted(rows, key=lambda r: r["name"])


def _names_fp(rows: list[dict]) -> str:
    return _json_fp([r["name"] for r in rows])


def _identity_fp(rows: list[dict]) -> str:
    return _json_fp([{"name": r["name"], "size": r["size"], "md5": r["md5"]} for r in rows])


def _assert_expected_current_missing(api, folder_id: str, role: str) -> dict:
    try:
        meta = _meta(api, folder_id)
    except HttpError as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status == 404:
            return {"pass": True, "role": role, "state": "NOT_FOUND_404", "folder_id": folder_id}
        raise
    raise RuntimeError(
        "RECOVERY_PROMOTION_PREPARE_OLD_CURRENT_UNEXPECTEDLY_EXISTS:"
        f"{role}:{meta.get('id')}:{meta.get('name')}:{meta.get('trashed')}"
    )


def _repo_pointer_hits(old_id: str, root: Path) -> list[str]:
    hits: list[str] = []
    skip_roots = {".git", ".pytest_cache", "__pycache__", ".venv", "venv"}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in skip_roots for part in path.parts):
            continue
        try:
            if path.stat().st_size > 5_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if old_id in text:
            hits.append(path.relative_to(root).as_posix())
    return sorted(set(hits))


def _validate_final_checkpoint_candidate(writer_api, req: dict) -> dict:
    run_id = str(req["run_folder_id"])
    final_id = str(req["final_report_file_id"])
    checkpoint_id = str(req["checkpoint_file_id"])
    candidate_id = str(req["candidate_folder_id"])
    expected_sha = str(req["expected_recovery_github_sha"])

    run_meta = _meta(writer_api, run_id)
    if run_meta.get("mimeType") != cr.FOLDER_MIME or FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID not in list(run_meta.get("parents") or []):
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_RUN_PARENT_MISMATCH")

    run_children = cr._list_children(writer_api, run_id)
    child_by_id = {str(x.get("id") or ""): x for x in run_children}
    if final_id not in child_by_id or str(child_by_id[final_id].get("name") or "") != "RECOVERY_PREPARE_FINAL.json":
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_FINAL_POINTER_MISMATCH")
    if checkpoint_id not in child_by_id or not str(child_by_id[checkpoint_id].get("name") or "").startswith("CHECKPOINT_"):
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CHECKPOINT_POINTER_MISMATCH")

    final = cr._download_json(writer_api, final_id)
    checkpoint = cr._download_json(writer_api, checkpoint_id)
    if final.get("schema") != cr.FINAL_SCHEMA or final.get("pass") is not True:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_FINAL_NOT_PASS")
    if final.get("status") != "PASS_PREPARED_STAGING_ONLY" or final.get("mode") != "PREPARE_ONLY_NO_CANONICAL_WRITE":
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_FINAL_STATE_MISMATCH")
    if str(final.get("github_sha") or "") != expected_sha or str(final.get("run_folder_id") or "") != run_id:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_FINAL_IDENTITY_MISMATCH")
    if str(final.get("canonical_current_expected_old_id") or "") != FROZEN_CURRENT_FOLDER_DRIVE_ID:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_OLD_CURRENT_ID_MISMATCH")
    if final.get("canonical_write_performed") is not False or final.get("raw_write_performed") is not False or final.get("promotion_authorized") is not False:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_FINAL_FORBIDDEN_WRITE_FLAG")

    if checkpoint.get("schema") != cr.CHECKPOINT_SCHEMA or checkpoint.get("status") != "PASS_PREPARED":
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CHECKPOINT_NOT_PASS")
    if str(checkpoint.get("github_sha") or "") != expected_sha or str(checkpoint.get("run_folder_id") or "") != run_id:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CHECKPOINT_IDENTITY_MISMATCH")
    if str(checkpoint.get("candidate_current_folder_id") or "") != candidate_id:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CHECKPOINT_CANDIDATE_MISMATCH")
    if str(checkpoint.get("request_fingerprint") or "") != str(final.get("request_fingerprint") or ""):
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_REQUEST_FINGERPRINT_MISMATCH")
    if str(checkpoint.get("evidence_fingerprint") or "") != str(final.get("evidence_fingerprint") or ""):
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_EVIDENCE_FINGERPRINT_MISMATCH")
    if checkpoint.get("canonical_write_performed") is not False or checkpoint.get("raw_write_performed") is not False:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CHECKPOINT_FORBIDDEN_WRITE_FLAG")

    assembly = final.get("assembly") or {}
    if assembly.get("pass") is not True or str(assembly.get("candidate_folder_id") or "") != candidate_id:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_ASSEMBLY_CANDIDATE_MISMATCH")
    if assembly.get("candidate_folder_role") != "STAGING_ONLY_NOT_CANONICAL_CURRENT":
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CANDIDATE_ROLE_MISMATCH")

    candidate_meta = _meta(writer_api, candidate_id)
    if candidate_meta.get("mimeType") != cr.FOLDER_MIME or run_id not in list(candidate_meta.get("parents") or []):
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CANDIDATE_PARENT_MISMATCH")

    candidate_children = cr._list_children(writer_api, candidate_id)
    folders = [x for x in candidate_children if x.get("mimeType") == cr.FOLDER_MIME]
    names = sorted(str(x.get("name") or "") for x in folders)
    if names != sorted(EXPECTED_LOGICAL) or len(folders) != len(EXPECTED_LOGICAL):
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_LOGICAL_FOLDER_SET_MISMATCH")

    live: dict[str, dict] = {}
    for logical in EXPECTED_LOGICAL:
        rows = [x for x in folders if str(x.get("name") or "") == logical]
        if len(rows) != 1:
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_LOGICAL_CARDINALITY:{logical}:{len(rows)}")
        folder_id = str(rows[0].get("id") or "")
        expected_id = str((assembly.get("logical_folder_ids") or {}).get(logical) or "")
        if folder_id != expected_id:
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_LOGICAL_ID_MISMATCH:{logical}")
        files = _file_rows(writer_api, folder_id)
        expected_readback = (assembly.get("readback") or {}).get(logical) or {}
        if len(files) != int(expected_readback.get("file_count") or -1):
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_FILE_COUNT_DRIFT:{logical}")
        if _names_fp(files) != str(expected_readback.get("names_fingerprint") or ""):
            raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_NAMES_FINGERPRINT_DRIFT:{logical}")
        live[logical] = {
            "folder_id": folder_id,
            "file_count": len(files),
            "names_fingerprint": _names_fp(files),
            "identity_fingerprint_name_size_md5": _identity_fp(files),
            "total_bytes": sum(r["size"] for r in files),
        }

    return {
        "final": final,
        "checkpoint": checkpoint,
        "run_meta": run_meta,
        "candidate_meta": candidate_meta,
        "live_logical": live,
        "candidate_tree_identity_fingerprint": _json_fp(live),
    }


def build_prepare_report(*, repo_root: Path) -> dict:
    req = _load_request()
    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)

    reader_missing = _assert_expected_current_missing(reader_api, str(req["expected_missing_current_folder_id"]), "READER")
    writer_missing = _assert_expected_current_missing(writer_api, str(req["expected_missing_current_folder_id"]), "WRITER")

    validated = _validate_final_checkpoint_candidate(writer_api, req)

    staging_meta = _meta(writer_api, str(req["parity_staging_folder_id"]))
    if staging_meta.get("mimeType") != cr.FOLDER_MIME:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_STAGING_NOT_FOLDER")
    staging_parents = list(staging_meta.get("parents") or [])
    if staging_parents != [str(req["canonical_parent_folder_id"])]:
        raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_STAGING_PARENT_MISMATCH:{staging_parents}")

    parent_meta = _meta(writer_api, str(req["canonical_parent_folder_id"]))
    if parent_meta.get("mimeType") != cr.FOLDER_MIME or str(parent_meta.get("name") or "") != CANONICAL_PARENT_NAME:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_CANONICAL_PARENT_IDENTITY_MISMATCH")

    siblings = cr._list_children(writer_api, str(req["canonical_parent_folder_id"]))
    exact_name = [x for x in siblings if str(x.get("name") or "") == CANONICAL_ROOT_NAME and not bool(x.get("trashed"))]
    if exact_name:
        raise RuntimeError(f"RECOVERY_PROMOTION_PREPARE_CANONICAL_NAME_ALREADY_PRESENT:{len(exact_name)}")

    pointer_hits = _repo_pointer_hits(str(req["expected_missing_current_folder_id"]), repo_root)
    if not pointer_hits:
        raise RuntimeError("RECOVERY_PROMOTION_PREPARE_OLD_POINTER_NOT_FOUND_IN_REPO")

    live = validated["live_logical"]
    total_files = sum(int(v["file_count"]) for v in live.values())
    total_bytes = sum(int(v["total_bytes"]) for v in live.values())
    provisional_name = f"{CANONICAL_ROOT_NAME}__RECOVERY_TXN_<UTC>_<NEW_ID>"

    report = {
        "schema": RESULT_SCHEMA,
        "status": "PASS_PREPARED_PROOF_ONLY_CANONICAL_WRITE_STILL_UNAUTHORIZED",
        "pass": True,
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
        "recovery": {
            "github_sha": str(req["expected_recovery_github_sha"]),
            "run_folder_id": str(req["run_folder_id"]),
            "final_report_file_id": str(req["final_report_file_id"]),
            "checkpoint_file_id": str(req["checkpoint_file_id"]),
            "candidate_folder_id": str(req["candidate_folder_id"]),
            "request_fingerprint": str(validated["final"].get("request_fingerprint") or ""),
            "evidence_fingerprint": str(validated["final"].get("evidence_fingerprint") or ""),
            "recovered_source_count": int(validated["final"].get("recovered_source_count") or 0),
        },
        "old_current": {
            "folder_id": str(req["expected_missing_current_folder_id"]),
            "reader": reader_missing,
            "writer": writer_missing,
            "expected_state": "MISSING_404",
        },
        "canonical_parent": {
            "folder_id": str(req["canonical_parent_folder_id"]),
            "folder_name": str(parent_meta.get("name") or ""),
            "staging_is_sibling_under_same_parent": True,
            "exact_canonical_name_currently_absent": True,
        },
        "candidate_readback": {
            "logical_folders": live,
            "tree_identity_fingerprint_name_size_md5": validated["candidate_tree_identity_fingerprint"],
            "total_file_count": total_files,
            "total_bytes": total_bytes,
        },
        "proposed_authorized_transaction": {
            "authorization_precondition": "MACHINE_READABLE_CANONICAL_PROMOTION_ALLOWED_TRUE_AND_CANONICAL_CURRENT_RECOVERY_COMMIT_AUTHORIZED_TRUE_PLUS_EXPLICIT_OWNER_AUTHORIZATION",
            "step_1_revalidate": "re-read CURRENT authority; old ID remains 404 via reader+writer; canonical parent identity unchanged; exact canonical name absent; exact candidate fingerprints unchanged",
            "step_2_create_provisional_root": {
                "parent_id": str(req["canonical_parent_folder_id"]),
                "provisional_name": provisional_name,
                "canonical_name_not_visible_yet": True,
            },
            "step_3_copy_candidate": "create the five logical folders under provisional root and server-side copy every candidate file by exact name",
            "step_4_provisional_readback": "require exact logical folder names, file counts, names fingerprints, and name+size+md5 identity fingerprints equal to candidate",
            "step_5_publish": f"rename the fully verified provisional root to exact canonical name {CANONICAL_ROOT_NAME}; capture the new immutable Drive folder ID",
            "step_6_post_publish_readback": "re-read new root by captured ID and by unique sibling name; revalidate parent/name/logical tree/name+size+md5 fingerprints",
            "step_7_pointer_migration": "replace all stale old-ID repo/control bindings with captured new ID in a governed mutation; fresh-read and post-mutation readback required before PRESTART",
            "step_8_prestart": "rerun exact-target LIGHTWEIGHT/DYNAMIC PRESTART; heavy execution remains closed until that gate and Machine1 assigned-date gates pass",
        },
        "rollback_contract": {
            "before_publish_failure": "trash/delete only the newly-created provisional root; canonical name remains absent",
            "after_publish_before_pointer_commit_failure": "rename new root back to recovery provisional name, verify canonical exact name absent, then trash/delete that new root; old missing state restored",
            "after_pointer_commit_failure": "revert pointer mutation to old expected-missing state only after canonical root rollback readback; never leave repo pointer claiming an unverified root",
            "raw_rollback_needed": False,
            "old_current_restore_possible": False,
        },
        "pointer_migration": {
            "old_folder_id": str(req["expected_missing_current_folder_id"]),
            "new_folder_id": None,
            "new_folder_id_state": "UNKNOWN_UNTIL_AUTHORIZED_CANONICAL_ROOT_CREATION",
            "repo_paths_containing_old_id": pointer_hits,
            "post_creation_repo_scan_required": True,
            "no_hardcoded_guessed_new_id_allowed": True,
        },
        "authorization": {
            "canonical_promotion_allowed": False,
            "canonical_current_recovery_commit_authorized": False,
            "raw_write_allowed": False,
            "heavy_behavior_research_allowed": False,
            "canonical_write_performed": False,
            "raw_write_performed": False,
            "promotion_performed": False,
        },
        "request_fingerprint": _json_fp(req),
    }
    report["prepare_fingerprint"] = _json_fp(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = build_prepare_report(repo_root=Path(args.repo_root).resolve())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("A1_RECOVERY_PROMOTION_PREPARE_JSON=" + json.dumps({
        "pass": report["pass"],
        "status": report["status"],
        "candidate_folder_id": report["recovery"]["candidate_folder_id"],
        "canonical_parent_folder_id": report["canonical_parent"]["folder_id"],
        "candidate_tree_identity_fingerprint": report["candidate_readback"]["tree_identity_fingerprint_name_size_md5"],
        "canonical_write_performed": False,
        "raw_write_performed": False,
        "promotion_performed": False,
    }, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
