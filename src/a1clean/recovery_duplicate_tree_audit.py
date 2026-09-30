from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .google_drive import build_drive_api

FOLDER_MIME = "application/vnd.google-apps.folder"


def _children(api, folder_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token = None
    while True:
        resp = (
            api.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                spaces="drive",
                fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,parents,modifiedTime)",
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


def _walk(api, folder_id: str, prefix: str = "") -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for item in sorted(_children(api, folder_id), key=lambda x: (x.get("name", ""), x.get("id", ""))):
        name = item.get("name") or item["id"]
        rel = f"{prefix}/{name}" if prefix else name
        if item.get("mimeType") == FOLDER_MIME:
            files.extend(_walk(api, item["id"], rel))
            continue
        files.append(
            {
                "id": item["id"],
                "path": rel,
                "name": name,
                "size": int(item.get("size") or 0),
                "md5": item.get("md5Checksum"),
                "mimeType": item.get("mimeType"),
                "modifiedTime": item.get("modifiedTime"),
            }
        )
    return files


def _tree_fingerprint(files: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: (x["path"], x["size"], x.get("md5") or "")):
        h.update(f'{f["path"]}|{f["size"]}|{f.get("md5") or "MISSING_MD5"}\n'.encode("utf-8"))
    return h.hexdigest()


def _recovered_origin_inventory(api, root_id: str) -> tuple[list[dict[str, Any]], dict[tuple[str, int, str], list[dict[str, Any]]], dict[tuple[str, int, str], list[dict[str, Any]]]]:
    all_files: list[dict[str, Any]] = []
    by_path: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    by_name: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    source_folders = [x for x in _children(api, root_id) if x.get("mimeType") == FOLDER_MIME]
    for src in sorted(source_folders, key=lambda x: (x.get("name", ""), x.get("id", ""))):
        logical_folders = [x for x in _children(api, src["id"]) if x.get("mimeType") == FOLDER_MIME]
        for logical in logical_folders:
            logical_name = logical.get("name") or logical["id"]
            for f in _walk(api, logical["id"], logical_name):
                rec = {**f, "origin_source_folder_id": src["id"], "origin_source_folder_name": src.get("name"), "origin_kind": "RECOVERED_SOURCES"}
                all_files.append(rec)
                if rec.get("md5"):
                    by_path[(rec["path"], rec["size"], rec["md5"])].append(rec)
                    by_name[(rec["name"], rec["size"], rec["md5"])].append(rec)
    return all_files, by_path, by_name


def _control_origin_inventory(api, root_id: str) -> tuple[list[dict[str, Any]], dict[tuple[str, int, str], list[dict[str, Any]]]]:
    files = _walk(api, root_id)
    by_name: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for f in files:
        if f.get("md5"):
            by_name[(f["name"], f["size"], f["md5"])].append({**f, "origin_kind": "COMMITTED_CONTROL_BUNDLE"})
    return files, by_name


def _drive_reference_hits(api, needle: str) -> list[dict[str, Any]]:
    # Drive fullText is used only as a conservative reference-discovery gate.
    # Failure to search is returned to caller as HOLD rather than being treated as zero references.
    safe = needle.replace("'", "\\'")
    q = f"fullText contains '{safe}' and trashed = false"
    hits: list[dict[str, Any]] = []
    token = None
    while True:
        resp = (
            api.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken,files(id,name,mimeType,parents,modifiedTime)",
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        hits.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return hits


def _origin_diag(o: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": o["id"],
        "path": o["path"],
        "name": o["name"],
        "size": o["size"],
        "md5": o.get("md5"),
        "origin_source_folder_id": o.get("origin_source_folder_id"),
        "origin_source_folder_name": o.get("origin_source_folder_name"),
    }


def audit(repo_root: Path, output: Path) -> dict[str, Any]:
    request_path = repo_root / "canonical-current-recovery-requests" / "duplicate-tree-audit-current.json"
    req = json.loads(request_path.read_text(encoding="utf-8"))
    if req.get("mode") != "READ_ONLY_METADATA_AUDIT":
        raise RuntimeError("DUPLICATE_TREE_AUDIT_MODE_NOT_READ_ONLY")
    if req.get("canonical_current_mutation_allowed") is not False or req.get("physical_delete_allowed_by_this_audit") is not False:
        raise RuntimeError("DUPLICATE_TREE_AUDIT_MUTATION_FLAG_FAIL")

    api = build_drive_api(read_write=False)
    recovered_files, recovered_by_path, recovered_by_name = _recovered_origin_inventory(api, req["recovered_sources_folder_id"])
    control_files, control_by_name = _control_origin_inventory(api, req["committed_control_bundle_folder_id"])

    recovered_same_basename: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in recovered_files:
        recovered_same_basename[rec["name"]].append(rec)

    allowed_reference_ids = set(req.get("allowed_nonactive_drive_reference_ids", []))
    candidate_results: list[dict[str, Any]] = []
    overall_pass = True

    for candidate_id in req["partial_candidate_folder_ids"]:
        candidate_files = _walk(api, candidate_id)
        matches: list[dict[str, Any]] = []
        missing_md5: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []

        for f in candidate_files:
            if not f.get("md5"):
                missing_md5.append(f)
                continue
            key_path = (f["path"], f["size"], f["md5"])
            key_name = (f["name"], f["size"], f["md5"])
            origins = recovered_by_path.get(key_path, [])
            match_rule = "RECOVERED_LOGICAL_PATH_SIZE_MD5"
            if not origins:
                origins = control_by_name.get(key_name, [])
                match_rule = "CONTROL_BASENAME_SIZE_MD5"
            if not origins:
                exact_name_content_hits = recovered_by_name.get(key_name, [])
                same_basename_hits = recovered_same_basename.get(f["name"], [])
                unmatched.append(
                    {
                        **f,
                        "diagnostic_exact_basename_size_md5_hits": [_origin_diag(o) for o in exact_name_content_hits],
                        "diagnostic_same_basename_hits": [_origin_diag(o) for o in same_basename_hits],
                    }
                )
                continue
            matches.append(
                {
                    "candidate_file_id": f["id"],
                    "candidate_path": f["path"],
                    "size": f["size"],
                    "md5": f["md5"],
                    "match_rule": match_rule,
                    "origin_ids": [o["id"] for o in origins],
                    "origin_paths": [o["path"] for o in origins],
                }
            )

        reference_search_error = None
        try:
            raw_hits = _drive_reference_hits(api, candidate_id)
        except Exception as exc:  # fail closed
            raw_hits = []
            reference_search_error = f"{type(exc).__name__}:{exc}"
        unexpected_hits = [h for h in raw_hits if h.get("id") not in allowed_reference_ids]
        candidate_pass = bool(candidate_files) and not missing_md5 and not unmatched and reference_search_error is None and not unexpected_hits
        overall_pass = overall_pass and candidate_pass
        candidate_results.append(
            {
                "candidate_folder_id": candidate_id,
                "file_count": len(candidate_files),
                "tree_fingerprint_name_size_md5": _tree_fingerprint(candidate_files),
                "matched_file_count": len(matches),
                "missing_md5_count": len(missing_md5),
                "unmatched_file_count": len(unmatched),
                "drive_reference_hit_count": len(raw_hits),
                "unexpected_drive_reference_hit_count": len(unexpected_hits),
                "reference_search_error": reference_search_error,
                "pass": candidate_pass,
                "matches": matches,
                "missing_md5": missing_md5,
                "unmatched": unmatched,
                "drive_reference_hits": raw_hits,
                "unexpected_drive_reference_hits": unexpected_hits,
            }
        )

    result = {
        "schema": "A1_CANONICAL_RECOVERY_DUPLICATE_TREE_AUDIT_RESULT_V1",
        "mode": "READ_ONLY_METADATA_AUDIT",
        "pass": overall_pass,
        "status": "PASS_DUPLICATE_TREE_PROOF_READ_ONLY" if overall_pass else "HOLD_DUPLICATE_TREE_PROOF_INCOMPLETE",
        "request": req,
        "origin_summary": {
            "recovered_source_file_count": len(recovered_files),
            "recovered_source_tree_fingerprint": _tree_fingerprint(recovered_files),
            "committed_control_file_count": len(control_files),
            "committed_control_tree_fingerprint": _tree_fingerprint(control_files),
        },
        "candidates": candidate_results,
        "mutation": {
            "drive_write_performed": False,
            "canonical_current_mutation": False,
            "physical_delete_performed": False,
            "raw_write_performed": False,
        },
        "next_gate": req["next_gate_on_pass"] if overall_pass else req["next_gate_on_hold"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", default=".")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = audit(Path(args.repo_root).resolve(), Path(args.output).resolve())
    print(json.dumps({"pass": result["pass"], "status": result["status"], "next_gate": result["next_gate"]}, sort_keys=True))
    return 0 if result["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
