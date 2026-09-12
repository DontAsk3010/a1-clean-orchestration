from __future__ import annotations

import math
from typing import Any

from .contracts import DiscoveryPlan, LANE_ID, PatternDiscoveryContractError
from .dtw_tslearn_lane import dtw_distance
from .packet import ParsedTickerDayPacket
from .ruptures_lane import segment
from .stumpy_lane import matrix_profile


INDEPENDENCE_ASSERTIONS = {
    "ai_semantic_labels_consumed": False,
    "ai_event_journey_objects_consumed": False,
    "outcomes_consumed": False,
    "trading_signal_created": False,
    "formula_stage_opened": False,
    "sampling_used": False,
    "synthetic_rows_created": False,
}


def _finite_or_state(value: Any) -> dict[str, Any]:
    number = float(value)
    if math.isnan(number):
        return {"value": None, "numeric_state": "NAN"}
    if math.isinf(number):
        return {"value": None, "numeric_state": "POSITIVE_INFINITY" if number > 0 else "NEGATIVE_INFINITY"}
    return {"value": number, "numeric_state": "FINITE"}


def _run_ruptures(packet: ParsedTickerDayPacket, spec) -> dict[str, Any]:
    values = packet.numeric_series(spec.field)
    breakpoints = [int(x) for x in segment(
        values,
        algorithm=spec.algorithm,
        model=spec.model,
        predict_kwargs=dict(spec.predict_kwargs),
        algorithm_kwargs=dict(spec.algorithm_kwargs),
    )]
    if not breakpoints:
        raise PatternDiscoveryContractError(f"RUPTURES_EMPTY_BREAKPOINTS:{spec.run_id}")
    if breakpoints != sorted(set(breakpoints)):
        raise PatternDiscoveryContractError(f"RUPTURES_BREAKPOINTS_NOT_STRICTLY_INCREASING:{spec.run_id}:{breakpoints}")
    if breakpoints[-1] != packet.row_count:
        raise PatternDiscoveryContractError(
            f"RUPTURES_FINAL_BREAKPOINT_NOT_PACKET_END:{spec.run_id}:{breakpoints[-1]}:{packet.row_count}"
        )
    if breakpoints[0] <= 0 or any(bp > packet.row_count for bp in breakpoints):
        raise PatternDiscoveryContractError(f"RUPTURES_BREAKPOINT_OUT_OF_RANGE:{spec.run_id}:{breakpoints}")

    segments: list[dict[str, Any]] = []
    start = 0
    for ordinal, end_exclusive in enumerate(breakpoints, start=1):
        end_inclusive = end_exclusive - 1
        segments.append(
            {
                "segment_ordinal": ordinal,
                "start_index": start,
                "end_index_inclusive": end_inclusive,
                "end_index_exclusive": end_exclusive,
                "length": end_exclusive - start,
                "source_range": packet.range_ref(start, end_inclusive),
            }
        )
        start = end_exclusive

    return {
        "run_id": spec.run_id,
        "tool": "RUPTURES",
        "purpose": "CHANGE_POINT_REGIME_SEGMENTATION_EVIDENCE",
        "field": spec.field,
        "algorithm": spec.algorithm,
        "model": spec.model,
        "algorithm_kwargs": dict(spec.algorithm_kwargs),
        "predict_kwargs": dict(spec.predict_kwargs),
        "input_length": len(values),
        "breakpoints_end_exclusive": breakpoints,
        "segments": segments,
        "interpretation": "UNASSIGNED_ALGORITHMIC_EVIDENCE_ONLY",
    }


def _run_stumpy(packet: ParsedTickerDayPacket, spec) -> dict[str, Any]:
    values = packet.numeric_series(spec.field)
    if spec.window > len(values):
        raise PatternDiscoveryContractError(
            f"STUMPY_WINDOW_EXCEEDS_PACKET:{spec.run_id}:WINDOW={spec.window}:ROWS={len(values)}"
        )
    profile = matrix_profile(values, window=spec.window)
    expected_rows = len(values) - spec.window + 1
    if len(profile) != expected_rows:
        raise PatternDiscoveryContractError(
            f"STUMPY_PROFILE_LENGTH_MISMATCH:{spec.run_id}:EXPECTED={expected_rows}:ACTUAL={len(profile)}"
        )

    rows: list[dict[str, Any]] = []
    for idx, profile_row in enumerate(profile):
        nearest = int(profile_row[1])
        row: dict[str, Any] = {
            "subsequence_index": idx,
            "query_range": packet.range_ref(idx, idx + spec.window - 1),
            "matrix_profile": _finite_or_state(profile_row[0]),
            "nearest_neighbor_index": nearest,
            "left_neighbor_index": int(profile_row[2]),
            "right_neighbor_index": int(profile_row[3]),
        }
        if nearest >= 0:
            if nearest + spec.window > packet.row_count:
                raise PatternDiscoveryContractError(
                    f"STUMPY_NEIGHBOR_OUT_OF_RANGE:{spec.run_id}:INDEX={idx}:NEIGHBOR={nearest}"
                )
            row["nearest_neighbor_range"] = packet.range_ref(nearest, nearest + spec.window - 1)
        else:
            row["nearest_neighbor_range"] = None
        rows.append(row)

    return {
        "run_id": spec.run_id,
        "tool": "STUMPY_MATRIX_PROFILE",
        "purpose": "MOTIF_DISCORD_SUBSEQUENCE_EVIDENCE",
        "field": spec.field,
        "window": spec.window,
        "input_length": len(values),
        "profile_row_count": len(rows),
        "profile_rows": rows,
        "interpretation": "UNASSIGNED_ALGORITHMIC_EVIDENCE_ONLY",
    }


def _run_dtw(packet: ParsedTickerDayPacket, spec) -> dict[str, Any]:
    left = packet.numeric_series(spec.left_field)
    right = packet.numeric_series(spec.right_field)
    result = _finite_or_state(dtw_distance(left, right))
    return {
        "run_id": spec.run_id,
        "tool": "DTW_TSLEARN",
        "purpose": "WITHIN_PACKET_FIELD_DISTANCE_PRIMITIVE",
        "scope": "WITHIN_PACKET_ONLY_NOT_CROSS_TICKER_CLUSTERING",
        "left_field": spec.left_field,
        "right_field": spec.right_field,
        "left_length": len(left),
        "right_length": len(right),
        "distance": result,
        "packet_range": packet.range_ref(0, packet.row_count - 1),
        "interpretation": "UNASSIGNED_ALGORITHMIC_EVIDENCE_ONLY",
    }


def run_discovery_plan(packet: ParsedTickerDayPacket, plan: DiscoveryPlan) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for spec in plan.ruptures:
        runs.append(_run_ruptures(packet, spec))
    for spec in plan.stumpy:
        runs.append(_run_stumpy(packet, spec))
    for spec in plan.dtw:
        runs.append(_run_dtw(packet, spec))

    return {
        "schema": "A1_ALGORITHMIC_PATTERN_DISCOVERY_PACKET_RESULT_V1",
        "lane_id": LANE_ID,
        "packet_identity": packet.identity.as_dict(),
        "packet_fingerprint": packet.packet_fingerprint,
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "independence_assertions": dict(INDEPENDENCE_ASSERTIONS),
        "run_count": len(runs),
        "runs": runs,
        "reconciliation_status": "ALGORITHMIC_ONLY_NOT_YET_RECONCILED_WITH_AI",
    }
