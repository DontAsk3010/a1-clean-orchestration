from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from googleapiclient.http import MediaIoBaseDownload

from .google_drive import build_drive_api

FOLDER_MIME = "application/vnd.google-apps.folder"


def _children(api, folder_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token = None
    while True:
        resp = api.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces="drive",
            fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,parents)",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return out


def _candidate_shards(api, candidate_id: str, folder_name: str, prefix: str) -> list[dict[str, Any]]:
    folders = [x for x in _children(api, candidate_id) if x.get("mimeType") == FOLDER_MIME and x.get("name") == folder_name]
    if len(folders) != 1:
        raise RuntimeError(f"EXPECTED_ONE_SHARD_FOLDER:{candidate_id}:{len(folders)}")
    rx = re.compile(rf"^{re.escape(prefix)}(\d{{4}})\.bin$")
    shards: list[dict[str, Any]] = []
    for f in _children(api, folders[0]["id"]):
        if f.get("mimeType") == FOLDER_MIME:
            continue
        m = rx.match(f.get("name") or "")
        if not m:
            continue
        shards.append({
            "id": f["id"],
            "name": f["name"],
            "index": int(m.group(1)),
            "size": int(f.get("size") or 0),
            "md5": f.get("md5Checksum"),
        })
    return sorted(shards, key=lambda x: x["index"])


class ChunkSink(io.RawIOBase):
    def __init__(self) -> None:
        super().__init__()
        self.last_size = 0
        self.last_md5: str | None = None
        self.full_sha256 = hashlib.sha256()
        self.total_size = 0

    def writable(self) -> bool:
        return True

    def write(self, b: bytes | bytearray) -> int:
        data = bytes(b)
        self.last_size = len(data)
        self.last_md5 = hashlib.md5(data).hexdigest()
        self.full_sha256.update(data)
        self.total_size += len(data)
        return len(data)


def prove(repo_root: Path, output: Path) -> dict[str, Any]:
    req_path = repo_root / "canonical-current-recovery-requests" / "raw-shard-reconstructability-current.json"
    req = json.loads(req_path.read_text(encoding="utf-8"))
    if req.get("mode") != "READ_ONLY_CANONICAL_RAW_CHUNK_PROOF":
        raise RuntimeError("RAW_SHARD_PROOF_MODE_FAIL")
    for k in ("drive_write_allowed", "canonical_current_mutation_allowed", "physical_delete_allowed_by_this_proof", "raw_write_allowed", "heavy_behavior_research_allowed"):
        if req.get(k) is not False:
            raise RuntimeError(f"RAW_SHARD_PROOF_MUTATION_FLAG_FAIL:{k}")

    api = build_drive_api(read_write=False)
    meta = api.files().get(
        fileId=req["canonical_raw_file_id"],
        fields="id,name,size,md5Checksum,mimeType",
        supportsAllDrives=True,
    ).execute()
    raw_size = int(meta.get("size") or 0)
    if meta.get("name") != req["canonical_raw_file_name"]:
        raise RuntimeError("RAW_SHARD_PROOF_RAW_NAME_FAIL")

    candidate_shards = {
        cid: _candidate_shards(api, cid, req["candidate_shard_folder_name"], req["candidate_shard_name_prefix"])
        for cid in req["partial_candidate_folder_ids"]
    }
    max_index = max((s["index"] for rows in candidate_shards.values() for s in rows), default=0)
    expected_chunks = (raw_size + req["chunk_size_bytes"] - 1) // req["chunk_size_bytes"]
    if max_index > expected_chunks:
        raise RuntimeError("RAW_SHARD_PROOF_CANDIDATE_INDEX_BEYOND_SOURCE")

    sink = ChunkSink()
    request = api.files().get_media(fileId=req["canonical_raw_file_id"], supportsAllDrives=True)
    downloader = MediaIoBaseDownload(sink, request, chunksize=int(req["chunk_size_bytes"]))
    source_chunks: list[dict[str, Any]] = []
    done = False
    idx = 0
    while not done:
        sink.last_size = 0
        sink.last_md5 = None
        status, done = downloader.next_chunk()
        idx += 1
        if sink.last_md5 is None:
            raise RuntimeError(f"RAW_SHARD_PROOF_EMPTY_CHUNK:{idx}")
        source_chunks.append({"index": idx, "size": sink.last_size, "md5": sink.last_md5, "progress": float(status.progress()) if status else None})

    full_sha = sink.full_sha256.hexdigest()
    source_by_index = {x["index"]: x for x in source_chunks}
    candidate_results: list[dict[str, Any]] = []
    all_pass = True
    for cid, shards in candidate_shards.items():
        comparisons: list[dict[str, Any]] = []
        for s in shards:
            src = source_by_index.get(s["index"])
            ok = bool(src) and s.get("md5") is not None and s["size"] == src["size"] and s["md5"] == src["md5"]
            comparisons.append({"candidate": s, "source_chunk": src, "match": ok})
        candidate_pass = bool(shards) and all(x["match"] for x in comparisons)
        all_pass = all_pass and candidate_pass
        candidate_results.append({
            "candidate_folder_id": cid,
            "shard_count": len(shards),
            "total_shard_bytes": sum(x["size"] for x in shards),
            "first_index": shards[0]["index"] if shards else None,
            "last_index": shards[-1]["index"] if shards else None,
            "is_complete_raw_partition": len(shards) == len(source_chunks) and sum(x["size"] for x in shards) == raw_size,
            "pass": candidate_pass,
            "comparisons": comparisons,
        })

    source_identity_pass = (
        raw_size == int(req["canonical_raw_expected_size"])
        and sink.total_size == raw_size
        and full_sha == req["canonical_raw_expected_sha256"]
        and len(source_chunks) == expected_chunks
    )
    all_pass = all_pass and source_identity_pass
    result = {
        "schema": "A1_CANONICAL_RECOVERY_RAW_SHARD_RECONSTRUCTABILITY_RESULT_V1",
        "pass": all_pass,
        "status": "PASS_RAW_SHARDS_EXACTLY_RECONSTRUCTIBLE_FROM_CANONICAL_RAW" if all_pass else "HOLD_RAW_SHARD_RECONSTRUCTABILITY_INCOMPLETE",
        "request": req,
        "canonical_raw": {
            "id": meta.get("id"),
            "name": meta.get("name"),
            "size": raw_size,
            "drive_md5": meta.get("md5Checksum"),
            "streamed_size": sink.total_size,
            "streamed_sha256": full_sha,
            "expected_sha256": req["canonical_raw_expected_sha256"],
            "chunk_size": req["chunk_size_bytes"],
            "chunk_count": len(source_chunks),
            "source_identity_pass": source_identity_pass,
            "chunks": source_chunks,
        },
        "candidates": candidate_results,
        "mutation": {
            "drive_write_performed": False,
            "canonical_current_mutation": False,
            "physical_delete_performed": False,
            "raw_write_performed": False,
            "payload_persisted_from_raw": False,
        },
        "next_gate": req["next_gate_on_pass"] if all_pass else req["next_gate_on_hold"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", default=".")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = prove(Path(args.repo_root).resolve(), Path(args.output).resolve())
    print(json.dumps({"pass": result["pass"], "status": result["status"], "next_gate": result["next_gate"]}, sort_keys=True))
    return 0 if result["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
