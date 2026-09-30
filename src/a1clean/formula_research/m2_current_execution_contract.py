from __future__ import annotations

from typing import Any, Mapping


SAFE_ATOMIC_UNITS_PER_SHARD = 1

_REQUIRED_REQUEST_FLAGS = {
    "machine2_full_scientific_restart_from_beginning_required": True,
    "old_pass_may_skip_current_reading_unit": False,
    "old_derived_semantic_checkpoint_completion_inherited": False,
    "date_ticker_record_timestamp_exact_resume_checkpoint_required": True,
    "per_source_only_checkpoint_is_not_sufficient_for_exact_resume": True,
    "strict_governed_chronological_restart_required": True,
    "progressive_current_checkpoint_lineage_must_start_new": True,
}

_REQUIRED_REF_FIELDS = (
    "selection_position",
    "manifest_index",
    "trading_date",
    "ticker",
    "data_row_count",
    "first_clock_time",
    "last_clock_time",
    "source_row_first",
    "source_row_last",
)


def validate_request_for_current_atomic_restart(request: Mapping[str, Any]) -> None:
    if request.get("enabled") is not True or request.get("restart_authorized") is not True:
        raise RuntimeError("M2_CURRENT_HEAVY_RESTART_NOT_AUTHORIZED")
    for key, expected in _REQUIRED_REQUEST_FLAGS.items():
        if request.get(key) is not expected:
            raise RuntimeError(f"M2_CURRENT_REQUEST_CONTRACT_MISMATCH:{key}")
    if request.get("formula_stage") != "CLOSED":
        raise RuntimeError("M2_CURRENT_FORMULA_STAGE_NOT_CLOSED")
    if request.get("grouping_stage") != "CLOSED_UNTIL_SEPARATELY_ADMITTED":
        raise RuntimeError("M2_CURRENT_GROUPING_STAGE_NOT_CLOSED")


def validate_exact_unit_ref(ref: Mapping[str, Any] | None, *, label: str) -> None:
    if not isinstance(ref, Mapping):
        raise RuntimeError(f"M2_CURRENT_EXACT_REF_MISSING:{label}")
    missing = [key for key in _REQUIRED_REF_FIELDS if ref.get(key) in (None, "")]
    if missing:
        raise RuntimeError(f"M2_CURRENT_EXACT_REF_FIELDS_MISSING:{label}:{missing}")
    first = int(ref["source_row_first"])
    last = int(ref["source_row_last"])
    count = int(ref["data_row_count"])
    if first < 0 or last < first or count <= 0:
        raise RuntimeError(f"M2_CURRENT_EXACT_REF_RANGE_INVALID:{label}")


def validate_checkpoint_exact_resume(checkpoint: Mapping[str, Any]) -> None:
    status = str(checkpoint.get("status") or "")
    completed = int(checkpoint.get("completed_units_in_current_date") or 0)
    if completed < 0:
        raise RuntimeError("M2_CURRENT_CHECKPOINT_COMPLETED_UNITS_INVALID")

    last_completed = checkpoint.get("last_completed")
    if completed == 0:
        if last_completed is not None:
            raise RuntimeError("M2_CURRENT_CHECKPOINT_LAST_COMPLETED_UNEXPECTED")
    else:
        validate_exact_unit_ref(last_completed, label="LAST_COMPLETED")

    next_ref = checkpoint.get("next_exact_resume_point")
    if status == "DATE_CLOSED":
        if next_ref is not None:
            raise RuntimeError("M2_CURRENT_DATE_CLOSED_HAS_NEXT_RESUME_POINT")
    else:
        validate_exact_unit_ref(next_ref, label="NEXT_EXACT_RESUME_POINT")
        if last_completed is not None:
            if int(next_ref["selection_position"]) != int(last_completed["selection_position"]) + 1:
                raise RuntimeError("M2_CURRENT_RESUME_POSITION_NOT_CONTIGUOUS")


def assert_safe_atomic_units_per_shard(value: int) -> None:
    if int(value) != SAFE_ATOMIC_UNITS_PER_SHARD:
        raise RuntimeError(
            f"M2_CURRENT_SAFE_ATOMIC_CHECKPOINT_REQUIRES_UNITS_PER_SHARD_{SAFE_ATOMIC_UNITS_PER_SHARD}"
        )
