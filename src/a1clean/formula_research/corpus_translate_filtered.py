from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from ..pattern_discovery.resilience import call_with_retry
from ..source_parity import _download_bytes, _list_children
from . import corpus_translate as base
from .lane2_translate import (
    EXPECTED_LANE2_PLAN_FINGERPRINT,
    EXPECTED_LANE2_PLAN_ID,
    FormulaTranslationContractError,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_target_stage1_manifest(manifest: Mapping[str, Any]) -> bool:
    """Return True only for the governed Stage-1 corpus plan.

    The Lane 2 evidence folder intentionally contains evidence from more than one
    governed plan (for example runtime-certification evidence). Formula Research
    must select only the exact Stage-1 corpus plan, while still failing closed if
    a manifest claims that plan id with a different fingerprint.
    """

    if manifest.get("plan_id") != EXPECTED_LANE2_PLAN_ID:
        return False
    if manifest.get("plan_fingerprint") != EXPECTED_LANE2_PLAN_FINGERPRINT:
        raise FormulaTranslationContractError("TARGET_STAGE1_PLAN_FINGERPRINT_MISMATCH")
    return True


def _load_target_input_manifests(reader_api, evidence_folder_id: str) -> list[dict[str, Any]]:
    items = call_with_retry(
        lambda: _list_children(
            reader_api,
            evidence_folder_id,
            fields="id,name,mimeType,size,md5Checksum,modifiedTime",
        ),
        operation=f"formula.list_input_evidence:{evidence_folder_id}",
    )
    rows: list[dict[str, Any]] = []
    target_name_token = f"__{EXPECTED_LANE2_PLAN_ID}__"
    for item in items:
        name = str(item.get("name") or "")
        if not name.endswith("__EVIDENCE_MANIFEST.json"):
            continue
        # Provider folder contains manifests for multiple governed plans. The
        # plan id is embedded in the governed filename, so skip unrelated plans
        # before downloading them. Content is still revalidated below.
        if target_name_token not in name:
            continue
        raw = call_with_retry(
            lambda item=item: _download_bytes(reader_api, str(item["id"])),
            operation=f"formula.read_manifest:{item['id']}",
        )
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_JSON_INVALID:{name}") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != base.INPUT_MANIFEST_SCHEMA:
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_SCHEMA_INVALID:{name}")

        # Non-target content under a target-looking governed filename is not
        # silently accepted; the exact plan and fingerprint are checked here.
        if not is_target_stage1_manifest(manifest):
            raise FormulaTranslationContractError(f"TARGET_STAGE1_FILENAME_CONTENT_PLAN_MISMATCH:{name}")

        assertions = manifest.get("independence_assertions")
        if not isinstance(assertions, Mapping):
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_ASSERTIONS_MISSING:{name}")
        base._validate_false_assertions(assertions, where=name)
        scope = manifest.get("scope") or {}
        if scope.get("scope_type") != "EXACT_TRADING_DATE" or not scope.get("trading_date"):
            raise FormulaTranslationContractError(f"INPUT_MANIFEST_NOT_EXACT_DATE:{name}")
        rows.append(
            {
                "item": item,
                "raw": raw,
                "sha256": _sha256(raw),
                "manifest": manifest,
                "trading_date": str(scope["trading_date"]),
                "source_name": str((manifest.get("source_identity") or {}).get("source_name") or ""),
            }
        )
    rows.sort(key=lambda row: (row["trading_date"], row["source_name"], str(row["item"]["name"])))
    return rows


def run_lane2_corpus_translation_filtered(**kwargs):
    """Run the existing restart-safe translator with exact-plan inventory selection."""

    original = base._load_input_manifests
    base._load_input_manifests = _load_target_input_manifests
    try:
        return base.run_lane2_corpus_translation(**kwargs)
    finally:
        base._load_input_manifests = original
