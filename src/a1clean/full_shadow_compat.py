from __future__ import annotations

import os

from . import full_shadow as _base
from .config import FROZEN_GENERATION_ID, FROZEN_IMPL_VERSION

# Capture the unwrapped implementation once. The compatibility wrapper temporarily
# monkey-patches _base._stable_source during the governed run; calling the live
# attribute from inside the wrapper would recurse back into this function.
_ORIGINAL_STABLE_SOURCE = _base._stable_source

# One explicitly audited predecessor run is allowed to resume after this wrapper-only
# reconciliation correction. This is deliberately narrow so arbitrary code revisions
# cannot inherit a prior checkpoint.
_COMPAT_PREDECESSOR_SHA = "f228d8e492ad8794a7a1ad3e32320d17c47ef09d"
_COMPAT_RUN_FOLDER = "FULL_SHADOW_PARITY_20260912T044220Z_f228d8e492ad_6c7758b30933"


def _stable_source_with_legacy_impl_fallback(obj: dict) -> dict:
    """Normalize one historical provenance omission, not analytical content.

    Some governed source-specific manifests predate population of
    data_plane_impl_version even though the governed GLOBAL manifest for the same
    source carries the frozen implementation version. All other stable fields remain
    strict, and the full-shadow final gate still compares every candidate stable map
    against the governed GLOBAL manifest without this fallback.
    """
    row = _ORIGINAL_STABLE_SOURCE(obj)
    if row.get("data_plane_impl_version") is None:
        row["data_plane_impl_version"] = FROZEN_IMPL_VERSION
    return row


def _matching_run_folders_compatible(api, staging_id: str, run_key: str) -> list[dict]:
    # run_key = <github-sha-prefix>_<source-universe-fingerprint-prefix>.
    # During this one audited wrapper correction, discover the existing run by the
    # unchanged source-universe fingerprint so already-PASS source checkpoints are
    # not recomputed.
    fingerprint_prefix = str(run_key).rsplit("_", 1)[-1]
    suffix = "_" + fingerprint_prefix
    return sorted(
        [
            item
            for item in _base._list_children(api, staging_id)
            if item.get("mimeType") == _base.FOLDER_MIME
            and str(item.get("name", "")).startswith("FULL_SHADOW_PARITY_")
            and str(item.get("name", "")).endswith(suffix)
        ],
        key=lambda item: str(item.get("name")),
        reverse=True,
    )


def _validate_resume_checkpoint_compatible(checkpoint: dict, preflight: dict) -> None:
    expected = {
        "schema": _base.CHECKPOINT_SCHEMA,
        "gate": _base.FULL_SHADOW_GATE,
        "generation_id": FROZEN_GENERATION_ID,
        "data_plane_impl_version": FROZEN_IMPL_VERSION,
        "source_universe_fingerprint": _base._source_universe_fingerprint(preflight),
    }
    for key, value in expected.items():
        if checkpoint.get(key) != value:
            raise RuntimeError(
                f"FULL_SHADOW_RESUME_IDENTITY_MISMATCH: key={key} expected={value!r} actual={checkpoint.get(key)!r}"
            )
    if checkpoint.get("required_sources") != _base._source_universe_rows(preflight):
        raise RuntimeError("FULL_SHADOW_RESUME_SOURCE_UNIVERSE_DRIFT")

    checkpoint_sha = str(checkpoint.get("github_sha") or "")
    current_sha = str(os.environ.get("GITHUB_SHA") or "LOCAL_NO_GITHUB_SHA").strip() or "LOCAL_NO_GITHUB_SHA"
    if checkpoint_sha == current_sha:
        return

    # Only the exact known HOLD run may cross this one wrapper revision boundary.
    if (
        checkpoint_sha == _COMPAT_PREDECESSOR_SHA
        and checkpoint.get("run_folder_name") == _COMPAT_RUN_FOLDER
        and checkpoint.get("status") in {"HOLD", "IN_PROGRESS"}
    ):
        return

    raise RuntimeError(
        f"FULL_SHADOW_RESUME_IDENTITY_MISMATCH: key=github_sha expected={current_sha!r} actual={checkpoint_sha!r}"
    )


def run_full_shadow_parity() -> dict:
    """Run the governed full-shadow gate with one narrow reconciliation compatibility fix.

    Frozen V2 semantics, source membership, content hashes, market indexes, semantic
    bundles, and final governed-global stable-map equality remain unchanged and strict.
    """
    old_stable_source = _base._stable_source
    old_matching = _base._matching_run_folders
    old_validate = _base._validate_resume_checkpoint
    _base._stable_source = _stable_source_with_legacy_impl_fallback
    _base._matching_run_folders = _matching_run_folders_compatible
    _base._validate_resume_checkpoint = _validate_resume_checkpoint_compatible
    try:
        return _base.run_full_shadow_parity()
    finally:
        _base._stable_source = old_stable_source
        _base._matching_run_folders = old_matching
        _base._validate_resume_checkpoint = old_validate
