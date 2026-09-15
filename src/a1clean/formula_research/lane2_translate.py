from __future__ import annotations

import statistics
from typing import Any, Iterable, Mapping

from ..pattern_discovery.contracts import fingerprint


EXPECTED_LANE2_PLAN_ID = "L2_CORPUS_STRUCTURAL_STAGE1_UNINTERPRETED_V1"
EXPECTED_LANE2_PLAN_FINGERPRINT = "ec06e5c6bbf856daafe10914e84a600b4b8c6460563d5f9a02db2f47791f63e1"


class FormulaTranslationContractError(ValueError):
    """Fail-closed contract violation while translating Lane 2 evidence."""


def _summary(values: Iterable[float | int]) -> dict[str, float | int | None]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {
        "count": len(numbers),
        "min": min(numbers),
        "median": statistics.median(numbers),
        "mean": statistics.fmean(numbers),
        "max": max(numbers),
    }


def _require_clean_stage1(result: Mapping[str, Any]) -> None:
    if result.get("schema") != "A1_ALGORITHMIC_PATTERN_DISCOVERY_PACKET_RESULT_V1":
        raise FormulaTranslationContractError("LANE2_PACKET_RESULT_SCHEMA_MISMATCH")
    if result.get("plan_id") != EXPECTED_LANE2_PLAN_ID:
        raise FormulaTranslationContractError("LANE2_PLAN_ID_MISMATCH")
    if result.get("plan_fingerprint") != EXPECTED_LANE2_PLAN_FINGERPRINT:
        raise FormulaTranslationContractError("LANE2_PLAN_FINGERPRINT_MISMATCH")

    assertions = result.get("independence_assertions")
    if not isinstance(assertions, Mapping):
        raise FormulaTranslationContractError("LANE2_INDEPENDENCE_ASSERTIONS_REQUIRED")
    forbidden_true = (
        "ai_semantic_labels_consumed",
        "ai_event_journey_objects_consumed",
        "outcomes_consumed",
        "trading_signal_created",
        "formula_stage_opened",
        "sampling_used",
        "synthetic_rows_created",
    )
    contaminated = [key for key in forbidden_true if bool(assertions.get(key))]
    if contaminated:
        raise FormulaTranslationContractError(f"LANE2_STAGE1_CONTAMINATION:{contaminated}")


def _ruptures_measurement(run: Mapping[str, Any]) -> dict[str, Any]:
    status = str(run.get("status") or "UNKNOWN")
    base = {
        "run_id": run.get("run_id"),
        "status": status,
        "field": run.get("field"),
        "purpose": run.get("purpose"),
    }
    if status != "EXECUTED":
        return {**base, "measurement_state": "NOT_EXECUTED", "reason": status}

    breakpoints = [int(value) for value in run.get("breakpoints_end_exclusive", [])]
    segments = list(run.get("segments", []) or [])
    segment_lengths = [int(row["length"]) for row in segments]
    input_length = int(run.get("input_length") or 0)
    if not breakpoints or breakpoints[-1] != input_length:
        raise FormulaTranslationContractError(f"RUPTURES_BOUNDARY_INVALID:{run.get('run_id')}")
    if len(segments) != len(breakpoints):
        raise FormulaTranslationContractError(f"RUPTURES_SEGMENT_COUNT_MISMATCH:{run.get('run_id')}")

    boundary_refs = []
    for segment in segments[1:]:
        source_range = segment.get("source_range") or {}
        start = source_range.get("start")
        if not isinstance(start, Mapping):
            raise FormulaTranslationContractError(f"RUPTURES_BOUNDARY_REF_MISSING:{run.get('run_id')}")
        boundary_refs.append(dict(start))

    return {
        **base,
        "measurement_state": "MEASURED",
        "input_length": input_length,
        "segment_count": len(segments),
        "internal_change_point_count": max(len(breakpoints) - 1, 0),
        "segment_length_summary": _summary(segment_lengths),
        "internal_change_point_refs": boundary_refs,
    }


def _stumpy_measurement(run: Mapping[str, Any]) -> dict[str, Any]:
    status = str(run.get("status") or "UNKNOWN")
    base = {
        "run_id": run.get("run_id"),
        "status": status,
        "field": run.get("field"),
        "purpose": run.get("purpose"),
        "window": run.get("window"),
    }
    if status != "EXECUTED":
        return {**base, "measurement_state": "NOT_EXECUTED", "reason": status}

    rows = list(run.get("profile_rows", []) or [])
    expected = int(run.get("profile_row_count") or 0)
    if len(rows) != expected:
        raise FormulaTranslationContractError(f"STUMPY_PROFILE_COUNT_MISMATCH:{run.get('run_id')}")

    profile_values: list[float] = []
    neighbor_distances: list[int] = []
    unmatched = 0
    for row in rows:
        profile = row.get("matrix_profile") or {}
        if profile.get("numeric_state") == "FINITE" and profile.get("value") is not None:
            profile_values.append(float(profile["value"]))
        nearest = int(row.get("nearest_neighbor_index", -1))
        query = int(row.get("subsequence_index", -1))
        if nearest >= 0 and query >= 0:
            neighbor_distances.append(abs(nearest - query))
        else:
            unmatched += 1

    return {
        **base,
        "measurement_state": "MEASURED",
        "input_length": int(run.get("input_length") or 0),
        "profile_row_count": expected,
        "finite_matrix_profile_summary": _summary(profile_values),
        "nearest_neighbor_index_distance_summary": _summary(neighbor_distances),
        "unmatched_neighbor_count": unmatched,
    }


def translate_lane2_packet_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Translate Stage-1 primitives into deterministic, non-semantic measurements.

    This function intentionally does not assign bullish/bearish meaning, outcome,
    score, threshold, rank, signal family, BUY/SELL state, TP/SL, or any final
    formula. It preserves exact Stage-1 lineage so later semantic reconciliation
    can join on source/ticker/date/time without hindsight backdating.
    """

    _require_clean_stage1(result)
    identity = result.get("packet_identity")
    if not isinstance(identity, Mapping):
        raise FormulaTranslationContractError("PACKET_IDENTITY_REQUIRED")

    rupture_measurements: list[dict[str, Any]] = []
    stumpy_measurements: list[dict[str, Any]] = []
    unsupported_runs: list[dict[str, Any]] = []
    for run in result.get("runs", []) or []:
        tool = str(run.get("tool") or "")
        if tool == "RUPTURES":
            rupture_measurements.append(_ruptures_measurement(run))
        elif tool == "STUMPY_MATRIX_PROFILE":
            stumpy_measurements.append(_stumpy_measurement(run))
        else:
            unsupported_runs.append(
                {"run_id": run.get("run_id"), "tool": tool, "status": run.get("status")}
            )

    payload: dict[str, Any] = {
        "schema": "A1_CURRENT_CLEAN_LANE2_STRUCTURAL_TRANSLATION_V1",
        "stage": "FORMULA_RESEARCH_TRANSLATION_MEASUREMENT_ONLY",
        "interpretation_state": "NON_SEMANTIC_STRUCTURAL_MEASUREMENT_ONLY",
        "packet_identity": dict(identity),
        "packet_fingerprint": result.get("packet_fingerprint"),
        "lane2_plan_id": result.get("plan_id"),
        "lane2_plan_fingerprint": result.get("plan_fingerprint"),
        "source_reconciliation_status": result.get("reconciliation_status"),
        "ruptures": rupture_measurements,
        "stumpy": stumpy_measurements,
        "unsupported_or_future_runs": unsupported_runs,
        "semantic_reconciliation_required_before_final_formula": True,
        "outcome_consumed": False,
        "signal_created": False,
        "threshold_created": False,
        "ranking_created": False,
    }
    payload["translation_fingerprint"] = fingerprint(payload)
    return payload
