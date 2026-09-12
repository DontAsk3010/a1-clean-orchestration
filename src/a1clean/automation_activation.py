from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from .canonical_promotion import AUTH_PHRASE as GATE_G_AUTH_PHRASE
from .canonical_promotion import CANONICAL, run_canonical_promotion
from .config import FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID
from .delta_artifacts import upload_json_payload
from .google_drive import build_drive_api
from .post_commit import run_post_commit_readback
from .source_parity import _create_folder

ACTIVATION_SCHEMA = "A1_GOVERNED_AUTOMATION_ACTIVATION_V1"
ACTIVATION_NAME = "A1_CLEAN_GOVERNED_AUTOMATION_ACTIVATION"
VERIFY = "VERIFY"
ACTIVATE_CANONICAL_IF_CHANGED = "ACTIVATE_CANONICAL_IF_CHANGED"
ACTIVATION_AUTH_PHRASE = "AUTHORIZE_GOVERNED_AUTOMATION_ACTIVATION"
ACTIVATION_RESULT = "AUTOMATION_ACTIVATION_RESULT.json"
MANUAL_TRIGGER_POLICY = "MANUAL_GOVERNED"
HOURLY_TRIGGER_POLICY = "HOURLY_LIGHTWEIGHT_WATCH"
_ALLOWED_TRIGGER_POLICIES = {MANUAL_TRIGGER_POLICY, HOURLY_TRIGGER_POLICY}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _trigger_policy() -> str:
    policy = str(os.environ.get("A1_AUTOMATION_TRIGGER_POLICY") or MANUAL_TRIGGER_POLICY).strip().upper()
    if policy not in _ALLOWED_TRIGGER_POLICIES:
        raise RuntimeError(f"UNSUPPORTED_AUTOMATION_TRIGGER_POLICY: {policy}")
    return policy


def _persist_result(result: dict) -> dict:
    writer_api = build_drive_api(read_write=True)
    folder_id = _create_folder(
        writer_api,
        parent_id=FROZEN_PARITY_STAGING_FOLDER_DRIVE_ID,
        name=f"AUTOMATION_ACTIVATION_{_stamp()}",
    )
    upload = upload_json_payload(
        writer_api,
        parent_id=folder_id,
        name=ACTIVATION_RESULT,
        payload=result,
    )
    if not upload.get("pass"):
        raise RuntimeError("AUTOMATION_ACTIVATION_RESULT_UPLOAD_FAILED")
    result["evidence_folder_id"] = folder_id
    result["result_upload"] = upload
    return result


def run_automation_activation(*, mode: str = VERIFY, authorization: str | None = None) -> dict:
    mode = str(mode).upper()
    if mode not in {VERIFY, ACTIVATE_CANONICAL_IF_CHANGED}:
        raise ValueError(f"Unsupported activation mode: {mode}")

    trigger_policy = _trigger_policy()
    unattended_authorized = trigger_policy == HOURLY_TRIGGER_POLICY

    readback_before = run_post_commit_readback()
    if readback_before.get("pass") is not True:
        raise RuntimeError("AUTOMATION_ACTIVATION_REQUIRES_POST_COMMIT_READBACK_PASS")

    base = {
        "pass": True,
        "schema": ACTIVATION_SCHEMA,
        "activation": ACTIVATION_NAME,
        "mode": mode,
        "post_commit_readback_status": readback_before.get("status"),
        "canonical_baseline_consumed": readback_before.get("canonical_baseline_consumed"),
        "pending_canonical_change_before": readback_before.get("pending_canonical_change"),
        "pending_source_changes_before": readback_before.get("pending_source_changes"),
        "pending_control_changes_before": readback_before.get("pending_control_changes"),
        "raw_write_authorized": False,
        "trigger_policy": trigger_policy,
        "unattended_scheduling_authorized": unattended_authorized,
    }

    if mode == VERIFY:
        return _persist_result(
            {
                **base,
                "status": "AUTOMATION_ACTIVATION_VERIFIED_NOT_ENABLED",
                "canonical_write_performed": False,
                "next_stage": "EXPLICIT_ACTIVATION_AUTHORIZATION",
                "note": (
                    "Post-commit baseline consumption is proven. VERIFY performs no canonical promotion. "
                    "Trigger policy reporting is informational in VERIFY mode."
                ),
            }
        )

    if authorization != ACTIVATION_AUTH_PHRASE:
        raise RuntimeError("GOVERNED_AUTOMATION_ACTIVATION_AUTHORIZATION_MISSING_OR_INCORRECT")

    promotion = None
    if readback_before.get("pending_canonical_change"):
        promotion = run_canonical_promotion(
            mode=CANONICAL,
            authorization=GATE_G_AUTH_PHRASE,
        )
        if promotion.get("pass") is not True or promotion.get("status") != "CANONICAL_PROMOTION_COMMITTED":
            raise RuntimeError("AUTOMATION_ACTIVATION_CANONICAL_PROMOTION_DID_NOT_COMMIT")

    readback_after = run_post_commit_readback()
    if readback_after.get("pass") is not True:
        raise RuntimeError("AUTOMATION_ACTIVATION_POST_PROMOTION_READBACK_FAILED")

    next_stage = "AUTOMATION_OPERATIONAL" if unattended_authorized else "AUTOMATION_TRIGGER_POLICY_DECISION"
    note = (
        "The durable automation cycle is active on the same production machine and canonical promotion path. "
        "Hourly unattended policy means only the lightweight metadata watch runs every hour; the heavy governed activation path runs only when the watch detects a material RAW/checkpoint change."
        if unattended_authorized
        else
        "The durable automation cycle is active on the same production machine and canonical promotion path. Manual governed triggering remains the active policy."
    )

    return _persist_result(
        {
            **base,
            "status": "GOVERNED_AUTOMATION_ACTIVATION_PASS",
            "canonical_write_performed": bool(promotion),
            "canonical_promotion_status": promotion.get("status") if promotion else "NOOP_ALREADY_CURRENT",
            "post_activation_readback_status": readback_after.get("status"),
            "pending_canonical_change_after": readback_after.get("pending_canonical_change"),
            "followup_delta_pending": bool(readback_after.get("pending_canonical_change")),
            "activation_ready": True,
            "next_stage": next_stage,
            "note": note,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="A1 CLEAN governed automation activation")
    parser.add_argument("--mode", choices=[VERIFY, ACTIVATE_CANONICAL_IF_CHANGED], default=VERIFY)
    parser.add_argument(
        "--authorization",
        default=os.environ.get("A1_AUTOMATION_ACTIVATION_AUTHORIZATION"),
    )
    args = parser.parse_args()
    result = run_automation_activation(mode=args.mode, authorization=args.authorization)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("pass") else 2


if __name__ == "__main__":
    raise SystemExit(main())
