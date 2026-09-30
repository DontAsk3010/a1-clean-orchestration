from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ..authority_bootstrap import DEFAULT_MANIFEST as DEFAULT_AUTHORITY_BOOTSTRAP_MANIFEST
from ..authority_bootstrap_drive_revision import run_authority_bootstrap_drive_revision
from ..google_drive import build_drive_api
from ..source_parity import _assert_folder, _download_json, _list_children
from .source_universe_cli import _atomic_write, _sha256
from .source_universe_manifest import build_source_universe_manifest, manifest_digest_is_valid


DEFAULT_STORAGE_SAFE_REBIND_REQUEST = Path(
    "canonical-current-recovery-requests/storage-safe-rebind-current.json"
)
FOLDER_MIME = "application/vnd.google-apps.folder"
DATA_PLANE_MANIFEST_SUFFIX = "__DATA_PLANE_MANIFEST.json"


def _load_storage_safe_rebind_request(path: Path) -> dict:
    request = json.loads(path.read_text(encoding="utf-8"))
    if request.get("schema") != "A1_CANONICAL_RECOVERY_STORAGE_SAFE_REBIND_REQUEST_V1":
        raise RuntimeError("SOURCE_UNIVERSE_STORAGE_REBIND_SCHEMA_MISMATCH")
    if request.get("enabled") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_STORAGE_REBIND_NOT_ENABLED")
    if request.get("mode") != "STORAGE_SAFE_MOVE_REBIND_ONLY":
        raise RuntimeError("SOURCE_UNIVERSE_STORAGE_REBIND_MODE_MISMATCH")
    if request.get("formula_stage") != "CLOSED":
        raise RuntimeError("SOURCE_UNIVERSE_FORMULA_STAGE_NOT_CLOSED")
    if request.get("heavy_behavior_research_allowed") is not False:
        raise RuntimeError("SOURCE_UNIVERSE_HEAVY_RESEARCH_MUST_REMAIN_DISABLED")
    if request.get("copy_allowed") is not False:
        raise RuntimeError("SOURCE_UNIVERSE_COPY_MUST_REMAIN_DISABLED")
    if request.get("source_regeneration_allowed") is not False:
        raise RuntimeError("SOURCE_UNIVERSE_REGENERATION_MUST_REMAIN_DISABLED")
    if request.get("raw_write_allowed") is not False:
        raise RuntimeError("SOURCE_UNIVERSE_RAW_WRITE_MUST_REMAIN_DISABLED")
    if request.get("canonical_raw_mutation_allowed") is not False:
        raise RuntimeError("SOURCE_UNIVERSE_CANONICAL_RAW_MUTATION_MUST_REMAIN_DISABLED")
    return request


def _single_named_folder(items: list[dict], name: str) -> dict:
    matches = [
        item
        for item in items
        if item.get("name") == name and item.get("mimeType") == FOLDER_MIME
    ]
    if len(matches) != 1:
        raise RuntimeError(f"SOURCE_UNIVERSE_FOLDER_CARDINALITY:name={name!r}:matches={len(matches)}")
    return matches[0]


def _single_data_plane_manifest(items: list[dict], source_folder_name: str) -> dict:
    matches = [
        item
        for item in items
        if item.get("mimeType") != FOLDER_MIME
        and str(item.get("name") or "").endswith(DATA_PLANE_MANIFEST_SUFFIX)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "SOURCE_UNIVERSE_DATA_PLANE_MANIFEST_CARDINALITY:"
            f"source_folder={source_folder_name!r}:matches={len(matches)}"
        )
    return matches[0]


def _recovered_source_state(api, request: dict) -> tuple[dict, dict]:
    data_plane_id = str(request.get("target_data_plane_folder_id") or "")
    data_plane_name = str(request.get("target_data_plane_folder_name") or "")
    recovered_id = str(request.get("recovered_sources_folder_id") or "")
    recovered_name = str(request.get("recovered_sources_folder_name") or "")
    if not all((data_plane_id, data_plane_name, recovered_id, recovered_name)):
        raise RuntimeError("SOURCE_UNIVERSE_STORAGE_REBIND_TOPOLOGY_FIELDS_MISSING")

    _assert_folder(api, data_plane_id, data_plane_name)
    recovered = _assert_folder(api, recovered_id, recovered_name)
    if data_plane_id not in set(recovered.get("parents") or []):
        raise RuntimeError(
            "SOURCE_UNIVERSE_RECOVERED_SOURCES_PARENT_MISMATCH:"
            f"expected_parent={data_plane_id}:actual={recovered.get('parents')}"
        )

    source_folders = [
        item
        for item in _list_children(api, recovered_id)
        if item.get("mimeType") == FOLDER_MIME
    ]
    if not source_folders:
        raise RuntimeError("SOURCE_UNIVERSE_RECOVERED_SOURCES_EMPTY")

    active_sources: list[dict] = []
    discovery_files: list[dict] = []
    expected_generation = str(request.get("expected_generation_id") or "")
    expected_impl = str(request.get("expected_data_plane_impl_version") or "")

    for source_folder in sorted(source_folders, key=lambda row: str(row.get("name") or "")):
        source_folder_id = str(source_folder.get("id") or "")
        source_folder_name = str(source_folder.get("name") or "")
        children = _list_children(api, source_folder_id)
        manifests_folder = _single_named_folder(children, "00_MANIFESTS")
        manifest_items = _list_children(api, manifests_folder["id"])
        manifest_file = _single_data_plane_manifest(manifest_items, source_folder_name)
        source_manifest = _download_json(api, manifest_file["id"])

        required = {
            "source_name": source_manifest.get("source_name"),
            "source_drive_id": source_manifest.get("source_drive_id"),
            "source_sha256": source_manifest.get("source_sha256"),
            "first_observed_date": source_manifest.get("first_observed_date"),
            "last_observed_date": source_manifest.get("last_observed_date"),
            "status": source_manifest.get("status"),
        }
        missing = sorted(key for key, value in required.items() if value in (None, ""))
        if missing:
            raise RuntimeError(
                "SOURCE_UNIVERSE_RECOVERED_MANIFEST_REQUIRED_METADATA_MISSING:"
                f"source_folder={source_folder_name!r}:missing={missing}"
            )
        if expected_generation and source_manifest.get("generation_id") != expected_generation:
            raise RuntimeError(
                "SOURCE_UNIVERSE_RECOVERED_GENERATION_DRIFT:"
                f"source={source_manifest.get('source_name')!r}:"
                f"expected={expected_generation!r}:actual={source_manifest.get('generation_id')!r}"
            )
        if expected_impl and source_manifest.get("data_plane_impl_version") != expected_impl:
            raise RuntimeError(
                "SOURCE_UNIVERSE_RECOVERED_IMPL_DRIFT:"
                f"source={source_manifest.get('source_name')!r}:"
                f"expected={expected_impl!r}:actual={source_manifest.get('data_plane_impl_version')!r}"
            )

        row = dict(source_manifest)
        row["recovered_source_folder_id"] = source_folder_id
        row["recovered_source_folder_name"] = source_folder_name
        row["recovery_manifest_drive_id"] = manifest_file["id"]
        row["delta_action"] = "REUSE_RECOVERED_SOURCE_NO_COPY_NO_REGEN"
        active_sources.append(row)
        discovery_files.append(
            {
                "drive_file_id": source_manifest.get("source_drive_id"),
                "name": source_manifest.get("source_name"),
                "identity_state": "RECOVERED_GOVERNED_SOURCE_MANIFEST",
                "recovered_source_folder_id": source_folder_id,
                "recovery_manifest_drive_id": manifest_file["id"],
            }
        )

    global_manifest = {
        "schema": "A1_RECOVERED_SOURCE_TOPOLOGY_GLOBAL_MANIFEST_V1",
        "generation_id": expected_generation,
        "data_plane_impl_version": expected_impl,
        "canonical_source_home_drive_id": recovered_id,
        "delta_refresh_id": "STORAGE_SAFE_REBIND_CURRENT_NO_COPY_NO_REGEN",
        "sources": active_sources,
        "source_count": len(active_sources),
        "storage_safe_rebind_request_schema": request.get("schema"),
        "storage_safe_rebind_target_data_plane_folder_id": data_plane_id,
        "storage_safe_rebind_recovered_sources_folder_id": recovered_id,
    }
    discovery = {
        "schema": "A1_RECOVERED_SOURCE_TOPOLOGY_DISCOVERY_V1",
        "files": discovery_files,
        "source_count": len(discovery_files),
        "fixed_source_count_as_invariant": False,
    }
    return global_manifest, discovery


def build_from_current_drive_controls(
    *,
    authority_lock_path: Path,
    storage_safe_rebind_request_path: Path = DEFAULT_STORAGE_SAFE_REBIND_REQUEST,
    discovery_time_utc: str | None = None,
    authority_sync: dict | None = None,
) -> dict:
    lock = json.loads(authority_lock_path.read_text(encoding="utf-8"))
    if lock.get("status") != "ACTIVE":
        raise RuntimeError("SOURCE_UNIVERSE_ACTIVE_AUTHORITY_LOCK_NOT_ACTIVE")
    if lock.get("prestart_completeness_gate_required") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_PRESTART_LOCK_REQUIRED")
    if lock.get("dynamic_source_universe_required") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_DYNAMIC_LOCK_REQUIRED")
    if lock.get("fixed_source_count_as_invariant_forbidden") is not True:
        raise RuntimeError("SOURCE_UNIVERSE_FIXED_COUNT_PROHIBITION_REQUIRED")
    if authority_sync is not None:
        if authority_sync.get("status") != "PASS" or authority_sync.get("full_authority_read_complete") is not True:
            raise RuntimeError("SOURCE_UNIVERSE_AUTHORITY_SYNC_NOT_PASS")

    rebind_request = _load_storage_safe_rebind_request(storage_safe_rebind_request_path)
    api = build_drive_api(read_write=False)
    global_manifest, discovery = _recovered_source_state(api, rebind_request)
    stamp = discovery_time_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest = build_source_universe_manifest(
        global_manifest=global_manifest,
        discovery=discovery,
        authority_revision="sha256:" + _sha256(authority_lock_path),
        discovery_time_utc=stamp,
        required_source_names=(),
        authority_sync=authority_sync,
    )
    if not manifest_digest_is_valid(manifest):
        raise RuntimeError("SOURCE_UNIVERSE_MANIFEST_SELF_DIGEST_FAIL")
    manifest["topology"] = {
        "mode": rebind_request.get("mode"),
        "data_plane_folder_id": rebind_request.get("target_data_plane_folder_id"),
        "recovered_sources_folder_id": rebind_request.get("recovered_sources_folder_id"),
        "copy_allowed": rebind_request.get("copy_allowed"),
        "source_regeneration_allowed": rebind_request.get("source_regeneration_allowed"),
        "raw_write_allowed": rebind_request.get("raw_write_allowed"),
        "heavy_behavior_research_allowed": rebind_request.get("heavy_behavior_research_allowed"),
    }
    # Recompute the self-digest after attaching governed topology provenance.
    manifest.pop("manifest_digest", None)
    from .source_universe_manifest import _digest

    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--authority-lock",
        type=Path,
        default=Path("governance/a1-clean-active-authority-lock.json"),
    )
    parser.add_argument(
        "--authority-bootstrap",
        type=Path,
        default=DEFAULT_AUTHORITY_BOOTSTRAP_MANIFEST,
    )
    parser.add_argument(
        "--storage-safe-rebind-request",
        type=Path,
        default=DEFAULT_STORAGE_SAFE_REBIND_REQUEST,
    )
    parser.add_argument("--authority-sync-proof", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--discovery-time-utc")
    args = parser.parse_args()

    # Hard ordering lock: full current authority is read and reconciled before
    # any governed source-universe discovery/data-plane control read.
    # Drive currentRevisionId is the runtime-comparable revision namespace;
    # Google Docs ANLCK revision tokens are retained as governance labels only.
    proof_path = args.authority_sync_proof or args.output.with_name("AUTHORITY_SYNC_PROOF.json")
    authority_sync = run_authority_bootstrap_drive_revision(
        manifest_path=args.authority_bootstrap,
        authority_lock_path=args.authority_lock,
        output_path=proof_path,
    )
    if authority_sync.get("status") != "PASS" or authority_sync.get("full_authority_read_complete") is not True:
        print(
            json.dumps(
                {
                    "schema": authority_sync.get("schema"),
                    "status": authority_sync.get("status"),
                    "authority_sync_proof": str(proof_path),
                    "revision_namespace": authority_sync.get("revision_namespace"),
                    "hold_count": len(authority_sync.get("holds") or []),
                    "holds": authority_sync.get("holds"),
                },
                sort_keys=True,
            )
        )
        return 3

    manifest = build_from_current_drive_controls(
        authority_lock_path=args.authority_lock,
        storage_safe_rebind_request_path=args.storage_safe_rebind_request,
        discovery_time_utc=args.discovery_time_utc,
        authority_sync=authority_sync,
    )
    _atomic_write(args.output, manifest)
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "status": manifest["status"],
                "source_count": manifest["source_count"],
                "manifest_digest": manifest["manifest_digest"],
                "authority_sync_status": manifest["authority_sync"]["status"],
                "authority_corpus_sha256": manifest["authority_sync"]["authority_corpus_sha256"],
                "authority_sync_proof": str(proof_path),
                "topology_mode": manifest.get("topology", {}).get("mode"),
                "hold_count": len(manifest["holds"]),
            },
            sort_keys=True,
        )
    )
    return 0 if manifest["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
