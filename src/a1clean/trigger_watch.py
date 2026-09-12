from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .config import (
    BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
    FROZEN_RAW_FOLDER_DRIVE_ID,
)
from .delta_artifacts import baseline_controls
from .google_drive import build_drive_api
from .source_parity import FOLDER_MIME, _download_json, _exact_named, _list_children
from .source_preflight import list_canonical_drive_sources

WATCH_SCHEMA = "A1_GOVERNED_AUTOMATION_TRIGGER_WATCH_V1"
WATCH_NAME = "A1_CLEAN_GOVERNED_AUTOMATION_TRIGGER_WATCH"
WATCH_NO_CHANGE = "WATCH_NO_MATERIAL_CHANGE"
WATCH_CHANGE = "WATCH_MATERIAL_CHANGE_DETECTED"


def _raw_current_projection(files: list[dict]) -> list[dict]:
    rows = []
    for item in files:
        rows.append(
            {
                "drive_file_id": item.get("id"),
                "name": item.get("name"),
                "drive_size_bytes": int(item["size"]) if item.get("size") is not None else None,
                "modified_time": item.get("modifiedTime"),
                "mime_type": item.get("mimeType"),
                "md5": item.get("md5Checksum"),
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("name")), str(row.get("drive_file_id"))))


def _raw_prior_projection(discovery: dict) -> list[dict]:
    rows = []
    for item in discovery.get("files") or []:
        rows.append(
            {
                "drive_file_id": item.get("drive_file_id"),
                "name": item.get("name"),
                "drive_size_bytes": item.get("drive_size_bytes"),
                "modified_time": item.get("modified_time"),
                "mime_type": item.get("mime_type") or "text/csv",
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("name")), str(row.get("drive_file_id"))))


def _checkpoint_current_projection(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        if item.get("mimeType") == FOLDER_MIME:
            continue
        name = str(item.get("name") or "")
        if not name.endswith("__CHECKPOINT_CURRENT.json"):
            continue
        rows.append(
            {
                "file_id": item.get("id"),
                "file_name": name,
                "modified_time": item.get("modifiedTime"),
                "size": int(item["size"]) if item.get("size") is not None else None,
                "md5": item.get("md5Checksum"),
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("file_name")), str(row.get("file_id"))))


def _checkpoint_prior_projection(ledger: dict) -> list[dict]:
    rows: list[dict] = []
    for state in (ledger.get("sources") or {}).values():
        provenance = state.get("checkpoint_provenance") or {}
        if not provenance.get("file_id"):
            continue
        rows.append(
            {
                "file_id": provenance.get("file_id"),
                "file_name": provenance.get("file_name"),
                "modified_time": provenance.get("modified_time"),
            }
        )
    return sorted(rows, key=lambda row: (str(row.get("file_name")), str(row.get("file_id"))))


def evaluate_watch(
    *,
    current_raw: list[dict],
    prior_raw: list[dict],
    current_checkpoints: list[dict],
    prior_checkpoints: list[dict],
) -> dict:
    """Decide whether the heavy governed activation path must run.

    This is deliberately metadata-only. It does not hash the local corpus, process
    source bytes, create behavior labels, or write canonical state. Any detected
    drift merely admits the existing permanent activation machine; that machine
    remains responsible for exact hashing, classification, reconciliation and
    fail-closed canonical promotion.
    """
    reasons: list[dict[str, Any]] = []

    current_raw_core = [
        {
            "drive_file_id": row.get("drive_file_id"),
            "name": row.get("name"),
            "drive_size_bytes": row.get("drive_size_bytes"),
            "modified_time": row.get("modified_time"),
            "mime_type": row.get("mime_type"),
        }
        for row in current_raw
    ]
    prior_raw_core = [
        {
            "drive_file_id": row.get("drive_file_id"),
            "name": row.get("name"),
            "drive_size_bytes": row.get("drive_size_bytes"),
            "modified_time": row.get("modified_time"),
            "mime_type": row.get("mime_type"),
        }
        for row in prior_raw
    ]
    if current_raw_core != prior_raw_core:
        reasons.append({"kind": "CANONICAL_RAW_METADATA_CHANGED"})

    current_names = [str(row.get("name")) for row in current_raw]
    if len(current_names) != len(set(current_names)):
        reasons.append({"kind": "CANONICAL_RAW_DUPLICATE_NAME_HINT"})
    if any(not row.get("md5") for row in current_raw):
        reasons.append({"kind": "CANONICAL_RAW_MD5_UNAVAILABLE_HINT"})

    current_checkpoint_core = [
        {
            "file_id": row.get("file_id"),
            "file_name": row.get("file_name"),
            "modified_time": row.get("modified_time"),
        }
        for row in current_checkpoints
    ]
    prior_checkpoint_core = [
        {
            "file_id": row.get("file_id"),
            "file_name": row.get("file_name"),
            "modified_time": row.get("modified_time"),
        }
        for row in prior_checkpoints
    ]
    if current_checkpoint_core != prior_checkpoint_core:
        reasons.append({"kind": "SEMANTIC_CHECKPOINT_METADATA_CHANGED"})

    activation_required = bool(reasons)
    return {
        "pass": True,
        "schema": WATCH_SCHEMA,
        "watch": WATCH_NAME,
        "status": WATCH_CHANGE if activation_required else WATCH_NO_CHANGE,
        "activation_required": activation_required,
        "reasons": reasons,
        "observed_raw_source_count": len(current_raw),
        "source_count_is_not_an_invariant": True,
        "observed_checkpoint_count": len(current_checkpoints),
        "heavy_local_hashing_performed": False,
        "canonical_write_performed": False,
        "raw_write_performed": False,
    }


def run_trigger_watch() -> dict:
    reader_api = build_drive_api(read_write=False)
    folders, _, _ = baseline_controls(reader_api)
    manifest_items = _list_children(
        reader_api,
        str(folders["00_MANIFESTS"]["id"]),
        fields="id,name,mimeType,size,md5Checksum,modifiedTime",
    )
    discovery_item = _exact_named(manifest_items, "GLOBAL_SOURCE_DISCOVERY.json")
    prior_discovery = _download_json(reader_api, discovery_item["id"])

    current_raw_files = list_canonical_drive_sources(reader_api, FROZEN_RAW_FOLDER_DRIVE_ID)
    current_raw = _raw_current_projection(current_raw_files)
    prior_raw = _raw_prior_projection(prior_discovery)

    behavior_items = _list_children(
        reader_api,
        BEHAVIOR_CONTROL_FOLDER_DRIVE_ID,
        fields="id,name,mimeType,size,md5Checksum,modifiedTime",
    )
    ledger_item = _exact_named(behavior_items, "PERSISTENT_SEMANTIC_RESEARCH_STATE.json")
    prior_ledger = _download_json(reader_api, ledger_item["id"])
    current_checkpoints = _checkpoint_current_projection(behavior_items)
    prior_checkpoints = _checkpoint_prior_projection(prior_ledger)

    return evaluate_watch(
        current_raw=current_raw,
        prior_raw=prior_raw,
        current_checkpoints=current_checkpoints,
        prior_checkpoints=prior_checkpoints,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="A1 CLEAN lightweight governed automation trigger watch")
    parser.add_argument("--result-file", default=None)
    args = parser.parse_args()
    result = run_trigger_watch()
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.result_file:
        path = Path(args.result_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
