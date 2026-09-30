from __future__ import annotations

import json
from datetime import datetime, timezone

from a1clean import canonical_recovery as cr
from a1clean.config import (
    FROZEN_CURRENT_FOLDER_DRIVE_ID,
    FROZEN_GENERATION_ID,
    FROZEN_IMPL_VERSION,
    FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
)
from a1clean.delta_artifacts import process_source_to_local, upload_json_payload
from a1clean.google_drive import build_drive_api
from a1clean.source_preflight import run_source_preflight


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
        if not _compatible_checkpoint(checkpoint, request_fp=request_fp, evidence_fp=evidence_fp):
            continue
        return folder, checkpoint
    return None, None


def _create_run(writer_api, *, request_fp: str, evidence_fp: str, first_source_name: str) -> tuple[dict, dict]:
    suffix = f"_{cr._github_sha()[:12]}_{request_fp[:12]}"
    run_folder_name = f"CANONICAL_CURRENT_RECOVERY_PREPARE_{cr._utc_stamp()}{suffix}"
    run_folder_id = cr._create_folder(
        writer_api,
        parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        name=run_folder_name,
    )
    sources_folder_id = cr._create_folder(writer_api, parent_id=run_folder_id, name="RECOVERED_SOURCES")
    checkpoint = {
        "schema": cr.CHECKPOINT_SCHEMA,
        "status": "IN_PROGRESS",
        "sequence": 0,
        "run_folder_id": run_folder_id,
        "run_folder_name": run_folder_name,
        "sources_folder_id": sources_folder_id,
        "github_sha": cr._github_sha(),
        "request_fingerprint": request_fp,
        "evidence_fingerprint": evidence_fp,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "completed_sources": {},
        "event_contract_tree_fingerprint": None,
        "next_exact_resume_source": first_source_name,
        "canonical_write_performed": False,
        "raw_write_performed": False,
    }
    cr._checkpoint_upload(writer_api, run_folder_id, checkpoint)
    return {"id": run_folder_id, "name": run_folder_name}, checkpoint


def _adopt_checkpoint_sha_if_safe(writer_api, checkpoint: dict) -> dict:
    current_sha = cr._github_sha()
    prior_sha = str(checkpoint.get("github_sha") or "")
    if prior_sha == current_sha:
        return checkpoint
    completed = dict(checkpoint.get("completed_sources") or {})
    if completed:
        raise RuntimeError(
            "RECOVERY_CROSS_SHA_COMPLETED_SOURCE_CARRY_FORBIDDEN: "
            f"prior={prior_sha} current={current_sha} completed={len(completed)}"
        )
    checkpoint = dict(checkpoint)
    checkpoint["resumed_from_github_sha"] = prior_sha
    checkpoint["github_sha"] = current_sha
    checkpoint["status"] = "IN_PROGRESS"
    checkpoint.pop("hold", None)
    checkpoint["sequence"] = int(checkpoint.get("sequence") or 0) + 1
    cr._checkpoint_upload(writer_api, checkpoint["run_folder_id"], checkpoint)
    return checkpoint


def _finalize(writer_api, *, request: dict, request_fp: str, evidence: dict, extras: list[dict], checkpoint: dict, missing_reader: dict, missing_writer: dict, resumed: bool) -> dict:
    completed = dict(checkpoint.get("completed_sources") or {})
    ordered = evidence["sources"]
    passed_ids = {sid for sid, row in completed.items() if row.get("pass") is True}
    expected_ids = {row["drive_id"] for row in ordered}
    if passed_ids != expected_ids:
        raise RuntimeError("RECOVERY_COMPLETED_SOURCE_MEMBERSHIP_HOLD")

    assembly = cr._assemble_candidate(
        writer_api,
        run_folder_id=checkpoint["run_folder_id"],
        completed=completed,
        evidence=ordered,
        controls_id=request["committed_control_bundle_folder_id"],
    )
    final = {
        "schema": cr.FINAL_SCHEMA,
        "pass": True,
        "status": "PASS_PREPARED_STAGING_ONLY",
        "mode": "PREPARE_ONLY_NO_CANONICAL_WRITE",
        "run_folder_id": checkpoint["run_folder_id"],
        "resumed_existing_run": resumed,
        "github_sha": cr._github_sha(),
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
        "canonical_current_expected_old_id": FROZEN_CURRENT_FOLDER_DRIVE_ID,
        "canonical_write_performed": False,
        "raw_write_performed": False,
        "promotion_authorized": False,
        "next_gate": "SEPARATE_GOVERNED_PROMOTION_AND_POST_PROMOTION_READBACK_REQUIRED",
    }
    uploaded = upload_json_payload(
        writer_api,
        parent_id=checkpoint["run_folder_id"],
        name="RECOVERY_PREPARE_FINAL.json",
        payload=final,
    )
    if uploaded.get("pass") is not True:
        raise RuntimeError("RECOVERY_FINAL_REPORT_UPLOAD_FAILED")

    checkpoint = dict(checkpoint)
    checkpoint["status"] = "PASS_PREPARED"
    checkpoint["next_exact_resume_source"] = None
    checkpoint["completed_sources"] = completed
    checkpoint["candidate_current_folder_id"] = assembly["candidate_folder_id"]
    checkpoint["canonical_write_performed"] = False
    checkpoint["raw_write_performed"] = False
    checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
    cr._checkpoint_upload(writer_api, checkpoint["run_folder_id"], checkpoint)
    return final


def run_one_source_step() -> dict:
    request = cr._load_request(cr.REQUEST_PATH)
    request_fp = cr._json_fingerprint(request)
    reader_api = build_drive_api(read_write=False)
    writer_api = build_drive_api(read_write=True)

    missing_reader = cr._assert_expected_current_missing(reader_api, request["expected_missing_current_folder_id"])
    missing_writer = cr._assert_expected_current_missing(writer_api, request["expected_missing_current_folder_id"])
    evidence = cr._load_full_shadow_evidence(reader_api, request["full_shadow_evidence_folder_id"])
    if int(request.get("baseline_source_count_observed") or -1) != evidence["source_count"]:
        raise RuntimeError("RECOVERY_REQUEST_BASELINE_SOURCE_COUNT_EVIDENCE_MISMATCH")

    preflight = run_source_preflight()
    if preflight.get("pass") is not True:
        raise RuntimeError("RECOVERY_RAW_SOURCE_PREFLIGHT_HOLD")
    selected, extras = cr._validate_raw_sources(preflight, evidence)
    selected_by_id = {str(r["drive_id"]): r for r in selected}

    run_folder, checkpoint = _find_compatible_run(
        writer_api,
        request_fp=request_fp,
        evidence_fp=evidence["evidence_fingerprint"],
    )
    resumed = run_folder is not None
    if run_folder is None:
        run_folder, checkpoint = _create_run(
            writer_api,
            request_fp=request_fp,
            evidence_fp=evidence["evidence_fingerprint"],
            first_source_name=evidence["sources"][0]["name"],
        )
    else:
        if checkpoint.get("status") == "PASS_PREPARED":
            final_item = cr._unique(cr._list_children(writer_api, run_folder["id"]), "RECOVERY_PREPARE_FINAL.json")
            final = cr._download_json(writer_api, final_item["id"])
            final["already_complete"] = True
            return final
        checkpoint = _adopt_checkpoint_sha_if_safe(writer_api, checkpoint)

    completed = dict(checkpoint.get("completed_sources") or {})
    ordered = evidence["sources"]
    incomplete = [row for row in ordered if completed.get(row["drive_id"], {}).get("pass") is not True]
    if not incomplete:
        return _finalize(
            writer_api,
            request=request,
            request_fp=request_fp,
            evidence=evidence,
            extras=extras,
            checkpoint=checkpoint,
            missing_reader=missing_reader,
            missing_writer=missing_writer,
            resumed=resumed,
        )

    expected = incomplete[0]
    pos = ordered.index(expected) + 1
    drive_id = expected["drive_id"]
    checkpoint = dict(checkpoint)
    checkpoint["status"] = "IN_PROGRESS"
    checkpoint["next_exact_resume_source"] = expected["name"]
    checkpoint.pop("hold", None)
    checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
    cr._checkpoint_upload(writer_api, checkpoint["run_folder_id"], checkpoint)

    print(f"A1_RECOVERY_SOURCE_START index={pos} name={expected['name']}", flush=True)
    root = None
    try:
        root, engine_result, manifest = process_source_to_local(
            selected=selected_by_id[drive_id],
            reader_api=reader_api,
        )
        print(f"A1_RECOVERY_SOURCE_ENGINE_PASS index={pos} name={expected['name']}", flush=True)
        comparison = cr._compare_regenerated_source(root, manifest, expected, reader_api)
        event_fp = comparison["event_contract_tree_fingerprint"]
        expected_event_fp = checkpoint.get("event_contract_tree_fingerprint")
        if expected_event_fp is None:
            expected_event_fp = event_fp
        elif event_fp != expected_event_fp:
            raise RuntimeError(f"RECOVERY_EVENT_CONTRACT_CROSS_SOURCE_DRIFT: {expected['name']}")
        staging = cr._persist_source(
            writer_api,
            parent_id=checkpoint["sources_folder_id"],
            source_index=pos,
            source_name=expected["name"],
            root=root,
        )
        print(f"A1_RECOVERY_SOURCE_STAGING_PASS index={pos} name={expected['name']}", flush=True)
        completed[drive_id] = {
            "pass": True,
            "source_index": pos,
            "source_name": expected["name"],
            "source_drive_id": drive_id,
            "source_sha256": comparison["source_sha256"],
            "physical_file_count": comparison["physical_file_count"],
            "semantic_file_count": comparison["semantic_file_count"],
            "event_contract_tree_fingerprint": event_fp,
            "historical_source_report_id": expected["historical_source_report_id"],
            "staging": staging,
            "engine_semantic_gate": engine_result.get("semantic_gate"),
        }
        checkpoint["completed_sources"] = completed
        checkpoint["event_contract_tree_fingerprint"] = expected_event_fp
        remaining = [row for row in ordered if completed.get(row["drive_id"], {}).get("pass") is not True]
        checkpoint["next_exact_resume_source"] = remaining[0]["name"] if remaining else None
        checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
        cr._checkpoint_upload(writer_api, checkpoint["run_folder_id"], checkpoint)
        print(f"A1_RECOVERY_SOURCE_CHECKPOINT_PASS index={pos} completed={len(completed)}", flush=True)
    except Exception as exc:
        checkpoint["status"] = "HOLD"
        checkpoint["completed_sources"] = completed
        checkpoint["hold"] = {
            "source": expected["name"],
            "reason": f"{type(exc).__name__}: {exc}",
            "at_utc": datetime.now(timezone.utc).isoformat(),
        }
        checkpoint["sequence"] = int(checkpoint["sequence"]) + 1
        cr._checkpoint_upload(writer_api, checkpoint["run_folder_id"], checkpoint)
        raise
    finally:
        if root is not None:
            cr.shutil.rmtree(root, ignore_errors=True)

    if len(completed) == len(ordered):
        return _finalize(
            writer_api,
            request=request,
            request_fp=request_fp,
            evidence=evidence,
            extras=extras,
            checkpoint=checkpoint,
            missing_reader=missing_reader,
            missing_writer=missing_writer,
            resumed=True,
        )

    return {
        "schema": cr.FINAL_SCHEMA,
        "pass": True,
        "status": "IN_PROGRESS_CHECKPOINTED",
        "run_folder_id": checkpoint["run_folder_id"],
        "github_sha": cr._github_sha(),
        "completed_source_count": len(completed),
        "total_source_count": len(ordered),
        "next_exact_resume_source": checkpoint.get("next_exact_resume_source"),
        "canonical_write_performed": False,
        "raw_write_performed": False,
        "promotion_authorized": False,
    }


def main() -> int:
    result = run_one_source_step()
    summary = {
        "pass": result.get("pass"),
        "status": result.get("status"),
        "run_folder_id": result.get("run_folder_id"),
        "github_sha": result.get("github_sha"),
        "completed_source_count": result.get("completed_source_count", result.get("recovered_source_count")),
        "total_source_count": result.get("total_source_count"),
        "next_exact_resume_source": result.get("next_exact_resume_source"),
        "candidate_folder_id": (result.get("assembly") or {}).get("candidate_folder_id"),
        "candidate_folder_role": (result.get("assembly") or {}).get("candidate_folder_role"),
        "canonical_write_performed": result.get("canonical_write_performed"),
        "raw_write_performed": result.get("raw_write_performed"),
        "promotion_authorized": result.get("promotion_authorized"),
    }
    print("A1_RECOVERY_STEP_JSON=" + json.dumps(summary, sort_keys=True, separators=(",", ":")), flush=True)
    return 0 if result.get("pass") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
