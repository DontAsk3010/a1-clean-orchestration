from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .google_drive import build_drive_api

FOLDER_MIME = "application/vnd.google-apps.folder"


def _get(api, file_id: str) -> dict[str, Any]:
    return (
        api.files()
        .get(
            fileId=file_id,
            fields="id,name,mimeType,size,md5Checksum,parents,modifiedTime,trashed",
            supportsAllDrives=True,
        )
        .execute()
    )


def _children(api, folder_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token = None
    while True:
        resp = (
            api.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,parents,modifiedTime,trashed)",
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return out


def _download_json(api, file_id: str) -> dict[str, Any]:
    data = api.files().get_media(fileId=file_id).execute()
    if isinstance(data, bytes):
        return json.loads(data.decode("utf-8-sig"))
    if hasattr(data, "read"):
        raw = data.read()
        return json.loads(raw.decode("utf-8-sig"))
    raise RuntimeError("REBIND_CHECKPOINT_DOWNLOAD_TYPE_UNSUPPORTED")


def _walk_records(api, root_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(folder_id: str) -> None:
        for item in sorted(_children(api, folder_id), key=lambda x: (x.get("name", ""), x.get("id", ""))):
            records.append(
                {
                    "id": item["id"],
                    "name": item.get("name"),
                    "mimeType": item.get("mimeType"),
                    "size": int(item.get("size") or 0),
                    "md5Checksum": item.get("md5Checksum"),
                    "parents": sorted(p for p in item.get("parents", []) if p),
                }
            )
            if item.get("mimeType") == FOLDER_MIME:
                visit(item["id"])

    visit(root_id)
    return records


def _fingerprint(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        sorted(records, key=lambda x: x["id"]),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_source_guard(api, source_ids: list[str]) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    for file_id in sorted(source_ids):
        item = _get(api, file_id)
        if item.get("trashed"):
            raise RuntimeError(f"REBIND_CANONICAL_SOURCE_TRASHED:{file_id}")
        rows.append(
            {
                "id": item["id"],
                "name": item.get("name"),
                "size": int(item.get("size") or 0),
                "md5Checksum": item.get("md5Checksum"),
                "modifiedTime": item.get("modifiedTime"),
                "parents": sorted(item.get("parents", [])),
            }
        )
    return rows, _fingerprint(rows)


def _validate_checkpoint(api, req: dict[str, Any], recovered_root_id: str) -> dict[str, Any]:
    checkpoint = _download_json(api, req["checkpoint_file_id"])
    if checkpoint.get("schema") != "A1_CANONICAL_CURRENT_RECOVERY_CHECKPOINT_V1":
        raise RuntimeError("REBIND_CHECKPOINT_SCHEMA_FAIL")
    if int(checkpoint.get("sequence") or -1) != int(req["checkpoint_sequence"]):
        raise RuntimeError("REBIND_CHECKPOINT_SEQUENCE_FAIL")
    if checkpoint.get("generation_id") != req["expected_generation_id"]:
        raise RuntimeError("REBIND_CHECKPOINT_GENERATION_FAIL")
    if checkpoint.get("data_plane_impl_version") != req["expected_data_plane_impl_version"]:
        raise RuntimeError("REBIND_CHECKPOINT_DATA_PLANE_IMPL_FAIL")

    completed = checkpoint.get("completed_sources") or {}
    if not completed:
        raise RuntimeError("REBIND_CHECKPOINT_COMPLETED_SOURCES_EMPTY")

    direct_children = {x["id"]: x for x in _children(api, recovered_root_id)}
    source_rows: list[dict[str, Any]] = []
    for source_id, row in sorted(completed.items()):
        if row.get("pass") is not True:
            raise RuntimeError(f"REBIND_CHECKPOINT_SOURCE_NOT_PASS:{source_id}")
        staging = row.get("staging") or {}
        source_folder_id = staging.get("folder_id")
        if not source_folder_id or source_folder_id not in direct_children:
            raise RuntimeError(f"REBIND_SOURCE_STAGING_FOLDER_NOT_DIRECT_CHILD:{source_id}:{source_folder_id}")
        source_folder = direct_children[source_folder_id]
        if source_folder.get("mimeType") != FOLDER_MIME:
            raise RuntimeError(f"REBIND_SOURCE_STAGING_NOT_FOLDER:{source_folder_id}")

        logical = staging.get("logical_folder_ids") or {}
        if set(logical) != {
            "00_MANIFESTS",
            "01_ACCESS_SHARDS",
            "02_SEMANTIC_BUNDLES",
            "03_MARKET_DAY_INDEX",
            "04_SEMANTIC_EVENT_CONTRACT",
        }:
            raise RuntimeError(f"REBIND_LOGICAL_FOLDER_KEYS_FAIL:{source_id}")
        source_children = {x["id"]: x for x in _children(api, source_folder_id)}
        for logical_name, logical_id in sorted(logical.items()):
            item = source_children.get(logical_id)
            if not item or item.get("mimeType") != FOLDER_MIME or item.get("name") != logical_name:
                raise RuntimeError(f"REBIND_LOGICAL_FOLDER_IDENTITY_FAIL:{source_id}:{logical_name}:{logical_id}")

        source_rows.append(
            {
                "source_drive_id": source_id,
                "source_name": row.get("source_name"),
                "source_sha256": row.get("source_sha256"),
                "source_folder_id": source_folder_id,
                "source_folder_name": source_folder.get("name"),
                "logical_folder_ids": logical,
            }
        )

    if len(direct_children) != len(source_rows):
        extra = sorted(set(direct_children) - {r["source_folder_id"] for r in source_rows})
        raise RuntimeError(f"REBIND_RECOVERED_ROOT_DIRECT_CHILD_CARDINALITY_FAIL:extra={extra}")

    return {
        "sequence": checkpoint["sequence"],
        "generation_id": checkpoint["generation_id"],
        "data_plane_impl_version": checkpoint["data_plane_impl_version"],
        "source_count": len(source_rows),
        "sources": source_rows,
    }


def _wait_for_parent_state(api, file_id: str, *, must_have: str, must_not_have: str, attempts: int = 12) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for _ in range(attempts):
        last = _get(api, file_id)
        parents = set(last.get("parents", []))
        if must_have in parents and must_not_have not in parents:
            return last
        time.sleep(2)
    raise RuntimeError(f"REBIND_PARENT_READBACK_TIMEOUT:{file_id}:{last}")


def execute(repo_root: Path, output: Path) -> dict[str, Any]:
    request_path = repo_root / "canonical-current-recovery-requests" / "storage-safe-rebind-current.json"
    req = json.loads(request_path.read_text(encoding="utf-8"))

    if req.get("schema") != "A1_CANONICAL_RECOVERY_STORAGE_SAFE_REBIND_REQUEST_V1":
        raise RuntimeError("REBIND_REQUEST_SCHEMA_FAIL")
    if req.get("enabled") is not True:
        raise RuntimeError("REBIND_REQUEST_DISABLED")
    if req.get("mode") != "STORAGE_SAFE_MOVE_REBIND_ONLY":
        raise RuntimeError("REBIND_REQUEST_MODE_FAIL")
    if req.get("copy_allowed") is not False or req.get("source_regeneration_allowed") is not False:
        raise RuntimeError("REBIND_COPY_OR_REGEN_LOCK_FAIL")
    for key in (
        "raw_write_allowed",
        "physical_delete_allowed",
        "canonical_raw_mutation_allowed",
        "heavy_behavior_research_allowed",
    ):
        if req.get(key) is not False:
            raise RuntimeError(f"REBIND_FORBIDDEN_FLAG_FAIL:{key}")
    if req.get("formula_stage") != "CLOSED":
        raise RuntimeError("REBIND_FORMULA_STAGE_FAIL")
    if req.get("allowed_drive_mutation") != "RECOVERED_SOURCES_TOP_LEVEL_PARENT_REBIND_ONLY":
        raise RuntimeError("REBIND_ALLOWED_MUTATION_FAIL")

    reader = build_drive_api(read_write=False)
    writer = build_drive_api(read_write=True)

    recovered_id = req["recovered_sources_folder_id"]
    old_parent_id = req["old_recovery_run_folder_id"]
    target_id = req["target_data_plane_folder_id"]

    recovered_pre = _get(reader, recovered_id)
    if recovered_pre.get("name") != req["recovered_sources_folder_name"] or recovered_pre.get("mimeType") != FOLDER_MIME:
        raise RuntimeError("REBIND_RECOVERED_ROOT_IDENTITY_FAIL")

    old_parent = _get(reader, old_parent_id)
    if old_parent.get("name") != req["old_recovery_run_folder_name"] or old_parent.get("mimeType") != FOLDER_MIME:
        raise RuntimeError("REBIND_OLD_PARENT_IDENTITY_FAIL")

    target = _get(reader, target_id)
    if target.get("name") != req["target_data_plane_folder_name"] or target.get("mimeType") != FOLDER_MIME:
        raise RuntimeError("REBIND_TARGET_DATA_PLANE_IDENTITY_FAIL")
    if req["target_machine2_folder_id"] not in set(target.get("parents", [])):
        raise RuntimeError("REBIND_TARGET_DATA_PLANE_PARENT_FAIL")
    machine2 = _get(reader, req["target_machine2_folder_id"])
    if machine2.get("name") != req["target_machine2_folder_name"] or machine2.get("mimeType") != FOLDER_MIME:
        raise RuntimeError("REBIND_MACHINE2_IDENTITY_FAIL")

    checkpoint = _validate_checkpoint(reader, req, recovered_id)
    source_ids = [row["source_drive_id"] for row in checkpoint["sources"]]

    subtree_pre = _walk_records(reader, recovered_id)
    subtree_pre_fp = _fingerprint(subtree_pre)
    canonical_pre_rows, canonical_pre_fp = _canonical_source_guard(reader, source_ids)

    pre_parents = sorted(recovered_pre.get("parents", []))
    pre_parent_set = set(pre_parents)
    drive_write_performed = False
    idempotent_existing_rebind = False

    if target_id in pre_parent_set and old_parent_id not in pre_parent_set:
        idempotent_existing_rebind = True
    elif old_parent_id in pre_parent_set and target_id not in pre_parent_set:
        writer.files().update(
            fileId=recovered_id,
            addParents=target_id,
            removeParents=old_parent_id,
            fields="id,name,parents,modifiedTime",
            supportsAllDrives=True,
        ).execute()
        drive_write_performed = True
    elif target_id in pre_parent_set and old_parent_id in pre_parent_set:
        writer.files().update(
            fileId=recovered_id,
            removeParents=old_parent_id,
            fields="id,name,parents,modifiedTime",
            supportsAllDrives=True,
        ).execute()
        drive_write_performed = True
    else:
        raise RuntimeError(f"REBIND_UNEXPECTED_PRE_PARENT_STATE:{pre_parents}")

    recovered_post = _wait_for_parent_state(
        reader,
        recovered_id,
        must_have=target_id,
        must_not_have=old_parent_id,
    )
    post_parents = sorted(recovered_post.get("parents", []))

    checkpoint_post = _validate_checkpoint(reader, req, recovered_id)
    subtree_post = _walk_records(reader, recovered_id)
    subtree_post_fp = _fingerprint(subtree_post)
    canonical_post_rows, canonical_post_fp = _canonical_source_guard(reader, source_ids)

    if checkpoint_post != checkpoint:
        raise RuntimeError("REBIND_CHECKPOINT_MAPPING_DRIFT")
    if subtree_post_fp != subtree_pre_fp or len(subtree_post) != len(subtree_pre):
        raise RuntimeError("REBIND_SUBTREE_FINGERPRINT_DRIFT")
    if canonical_post_fp != canonical_pre_fp or canonical_post_rows != canonical_pre_rows:
        raise RuntimeError("REBIND_CANONICAL_SOURCE_GUARD_DRIFT")

    result = {
        "schema": "A1_CANONICAL_RECOVERY_STORAGE_SAFE_REBIND_RESULT_V1",
        "pass": True,
        "status": "PASS_STORAGE_SAFE_MOVE_REBIND_EXACT_READBACK",
        "request": req,
        "checkpoint": checkpoint,
        "recovered_sources": {
            "folder_id": recovered_id,
            "folder_name": recovered_post.get("name"),
            "pre_parents": pre_parents,
            "post_parents": post_parents,
            "subtree_descendant_count": len(subtree_post),
            "subtree_fingerprint": subtree_post_fp,
            "source_count": checkpoint["source_count"],
        },
        "canonical_source_guard": {
            "source_count": len(canonical_post_rows),
            "fingerprint": canonical_post_fp,
            "unchanged": True,
        },
        "mutation": {
            "drive_write_performed": drive_write_performed,
            "idempotent_existing_rebind": idempotent_existing_rebind,
            "mutation_scope": "RECOVERED_SOURCES_TOP_LEVEL_PARENT_ONLY",
            "copy_performed": False,
            "source_regeneration_performed": False,
            "child_mutation_performed": False,
            "physical_delete_performed": False,
            "canonical_raw_mutation": False,
            "raw_write_performed": False,
            "heavy_behavior_research_performed": False,
        },
        "next_gate": req["next_gate_on_pass"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", default=".")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = execute(Path(args.repo_root).resolve(), Path(args.output).resolve())
    print(json.dumps({"pass": result["pass"], "status": result["status"], "next_gate": result["next_gate"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
