from __future__ import annotations

from pathlib import Path
from typing import Any

from . import canonical_recovery as _base
from .source_parity import FOLDER_MIME, _download_json, _list_children


def load_full_shadow_evidence_exact(api: Any, folder_id: str) -> dict:
    """Load only evidence explicitly selected by the final PASS report.

    Historical retries may leave same-named SRC_* folders in the immutable shadow
    run. Those orphan attempts are valid audit evidence but are not members of the
    final PASS set unless FULL_SHADOW_PARITY_FINAL.json points to their exact IDs.
    """
    root = _list_children(api, folder_id)
    final_item = _base._unique(root, "FULL_SHADOW_PARITY_FINAL.json")
    final = _download_json(api, final_item["id"])
    if final.get("pass") is not True:
        raise RuntimeError("RECOVERY_FULL_SHADOW_FINAL_NOT_PASS")

    summaries = list(final.get("source_summaries") or [])
    expected_count = int(final.get("completed_source_count") or -1)
    if expected_count < 1 or len(summaries) != expected_count:
        raise RuntimeError("RECOVERY_FINAL_SUMMARY_COUNT_MISMATCH")

    root_by_id = {str(item.get("id") or ""): item for item in root}
    sources: list[dict] = []
    seen_drive_ids: set[str] = set()
    seen_evidence_folders: set[str] = set()

    for summary in summaries:
        if summary.get("pass") is not True:
            raise RuntimeError(f"RECOVERY_FINAL_SOURCE_SUMMARY_NOT_PASS:{summary.get('name')}")
        expected_drive_id = str(summary.get("drive_id") or "")
        expected_name = str(summary.get("name") or "")
        evidence_folder_id = str(summary.get("evidence_folder_id") or "")
        source_report_file_id = str(summary.get("source_report_file_id") or "")
        if not expected_drive_id or not expected_name or not evidence_folder_id or not source_report_file_id:
            raise RuntimeError(f"RECOVERY_FINAL_SOURCE_POINTER_MISSING:{expected_name or expected_drive_id}")
        if expected_drive_id in seen_drive_ids:
            raise RuntimeError(f"RECOVERY_FINAL_DUPLICATE_SOURCE:{expected_drive_id}")
        if evidence_folder_id in seen_evidence_folders:
            raise RuntimeError(f"RECOVERY_FINAL_DUPLICATE_EVIDENCE_FOLDER:{evidence_folder_id}")

        folder = root_by_id.get(evidence_folder_id)
        if not folder or folder.get("mimeType") != FOLDER_MIME:
            raise RuntimeError(f"RECOVERY_FINAL_EVIDENCE_FOLDER_NOT_DIRECT_CHILD:{expected_name}:{evidence_folder_id}")

        items = _list_children(api, evidence_folder_id)
        report_item = _base._unique(items, "SOURCE_PARITY_REPORT.json")
        if str(report_item.get("id") or "") != source_report_file_id:
            raise RuntimeError(f"RECOVERY_FINAL_SOURCE_REPORT_POINTER_MISMATCH:{expected_name}")
        report = _download_json(api, source_report_file_id)
        if report.get("pass") is not True:
            raise RuntimeError(f"RECOVERY_SOURCE_EVIDENCE_NOT_PASS:{expected_name}")

        source = report.get("source") or {}
        checks = report.get("checks") or {}
        drive_id = str(source.get("drive_id") or "")
        name = str(source.get("name") or "")
        if drive_id != expected_drive_id or name != expected_name:
            raise RuntimeError(f"RECOVERY_FINAL_SOURCE_IDENTITY_MISMATCH:{expected_name}")

        stable = (checks.get("source_manifest_stable_fields") or {}).get("candidate")
        if not isinstance(stable, dict):
            raise RuntimeError(f"RECOVERY_STABLE_SOURCE_EVIDENCE_MISSING:{name}")
        summary_stable = summary.get("candidate_stable_source")
        if isinstance(summary_stable, dict) and stable != summary_stable:
            raise RuntimeError(f"RECOVERY_FINAL_STABLE_SOURCE_MISMATCH:{name}")

        physical = _base._evidence_family(checks.get("physical_shards_exact_md5") or {})
        semantic = _base._evidence_family(checks.get("semantic_bundles_exact_md5") or {})
        if int(summary.get("physical_shards") or -1) != len(physical):
            raise RuntimeError(f"RECOVERY_FINAL_PHYSICAL_COUNT_MISMATCH:{name}")
        if int(summary.get("semantic_bundles") or -1) != len(semantic):
            raise RuntimeError(f"RECOVERY_FINAL_SEMANTIC_COUNT_MISMATCH:{name}")

        stem = Path(name).stem
        sources.append({
            "source_index": int(report.get("source_index") or 0),
            "name": name,
            "drive_id": drive_id,
            "size": int(source.get("size") or -1),
            "drive_md5": str(source.get("drive_md5") or "").lower(),
            "stable_source": stable,
            "physical": physical,
            "semantic": semantic,
            "semantic_manifest_evidence_id": _base._unique(items, f"CANDIDATE__{stem}__SEMANTIC_BUNDLES_MANIFEST.json")["id"],
            "market_index_evidence_id": _base._unique(items, f"CANDIDATE__{stem}__MARKET_DAY_INDEX.json")["id"],
            "historical_source_report_id": source_report_file_id,
            "historical_evidence_folder_id": evidence_folder_id,
        })
        seen_drive_ids.add(drive_id)
        seen_evidence_folders.add(evidence_folder_id)

    sources.sort(key=lambda row: (row["source_index"], row["name"], row["drive_id"]))
    if len(sources) != expected_count:
        raise RuntimeError("RECOVERY_EVIDENCE_SOURCE_COUNT_MISMATCH")
    final_ids = {str(row.get("drive_id") or "") for row in summaries}
    if final_ids != seen_drive_ids:
        raise RuntimeError("RECOVERY_EVIDENCE_SOURCE_MEMBERSHIP_MISMATCH")

    compact = [{
        "source_index": row["source_index"],
        "name": row["name"],
        "drive_id": row["drive_id"],
        "size": row["size"],
        "drive_md5": row["drive_md5"],
        "stable_source": row["stable_source"],
        "physical": row["physical"],
        "semantic": row["semantic"],
        "historical_evidence_folder_id": row["historical_evidence_folder_id"],
        "historical_source_report_id": row["historical_source_report_id"],
    } for row in sources]
    return {
        "final": final,
        "sources": sources,
        "source_count": len(sources),
        "evidence_fingerprint": _base._json_fingerprint(compact),
    }


def run_canonical_current_recovery_prepare_exact_evidence(*args: Any, **kwargs: Any) -> dict:
    original = _base._load_full_shadow_evidence
    _base._load_full_shadow_evidence = load_full_shadow_evidence_exact
    try:
        return _base.run_canonical_current_recovery_prepare(*args, **kwargs)
    finally:
        _base._load_full_shadow_evidence = original
