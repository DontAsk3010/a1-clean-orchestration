from __future__ import annotations

from statistics import median
from typing import Any, Mapping, Sequence

from .telegram_mg_multiday_context_study import DayRecord


def _num(v: Any) -> float | None:
    return None if v is None else float(v)


def _segment(row: Mapping[str, Any]) -> str | None:
    if bool(row.get("regular_session1")):
        return "S1"
    if bool(row.get("regular_session2")):
        return "S2"
    return None


def _prefix_series(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, float] | None]:
    out: list[dict[str, float] | None] = []
    activity_sum = 0.0
    high_max: float | None = None
    low_min: float | None = None
    first_close: float | None = None
    valid = True
    for count, row in enumerate(rows, start=1):
        c = _num(row.get("close"))
        h = _num(row.get("high"))
        l = _num(row.get("low"))
        tv = _num(row.get("trade_value"))
        if None in (c, h, l, tv):
            valid = False
        if not valid:
            out.append(None)
            continue
        assert c is not None and h is not None and l is not None and tv is not None
        if first_close is None:
            first_close = c
        activity_sum += tv
        high_max = h if high_max is None else max(high_max, h)
        low_min = l if low_min is None else min(low_min, l)
        if first_close <= 0 or c <= 0 or low_min is None or low_min <= 0 or high_max is None:
            out.append(None)
            continue
        out.append({
            "activity_per_bar": activity_sum / count,
            "range_pct": (high_max / low_min - 1.0) * 100.0,
            "path_pct": (c / first_close - 1.0) * 100.0,
        })
    return out


def _by_segment(bars: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    out = {"S1": [], "S2": []}
    for row in bars:
        seg = _segment(row)
        if seg is not None:
            out[seg].append(row)
    return out


def build_history_context_series(
    *,
    bars: Sequence[Mapping[str, Any]],
    history_by_date: Mapping[str, DayRecord],
    prior_dates: Sequence[str],
) -> list[dict[str, Any] | None]:
    """Exact cached equivalent of repeated _history_context calls.

    Uses only current prefix through each index and exact completed prior dates.
    Missing prior ticker/date/session evidence yields None; nothing is imputed.
    """
    if not prior_dates:
        return [None] * len(bars)

    current_segments = _by_segment(bars)
    current_prefix = {seg: _prefix_series(rows) for seg, rows in current_segments.items()}

    prior_prefix: dict[str, dict[str, list[dict[str, float] | None]]] = {}
    for date in prior_dates:
        rec = history_by_date.get(date)
        if rec is None:
            return [None] * len(bars)
        seg_rows = _by_segment(rec.bars)
        prior_prefix[date] = {seg: _prefix_series(rows) for seg, rows in seg_rows.items()}

    counts = {"S1": 0, "S2": 0}
    result: list[dict[str, Any] | None] = []
    for row in bars:
        seg = _segment(row)
        if seg is None:
            result.append(None)
            continue
        counts[seg] += 1
        pos = counts[seg] - 1
        current = current_prefix[seg][pos] if pos < len(current_prefix[seg]) else None
        if current is None:
            result.append(None)
            continue

        priors: list[dict[str, float]] = []
        unavailable = False
        for date in prior_dates:
            series = prior_prefix[date][seg]
            if pos >= len(series) or series[pos] is None:
                unavailable = True
                break
            priors.append(series[pos])  # type: ignore[arg-type]
        if unavailable or not priors:
            result.append(None)
            continue

        med_activity = float(median(p["activity_per_bar"] for p in priors))
        med_range = float(median(p["range_pct"] for p in priors))
        med_path = float(median(p["path_pct"] for p in priors))
        activity_ratio = current["activity_per_bar"] / med_activity if med_activity > 0 else None
        range_ratio = current["range_pct"] / med_range if med_range > 0 else None
        if activity_ratio is None or range_ratio is None:
            result.append(None)
            continue
        path_delta = current["path_pct"] - med_path
        result.append({
            "session_segment": seg,
            "comparable_bar_count": counts[seg],
            "current_activity_per_bar": current["activity_per_bar"],
            "prior_median_activity_per_bar": med_activity,
            "activity_ratio": activity_ratio,
            "current_range_pct": current["range_pct"],
            "prior_median_range_pct": med_range,
            "range_ratio": range_ratio,
            "current_path_pct": current["path_pct"],
            "prior_median_path_pct": med_path,
            "path_delta_pct": path_delta,
            "activity_wake": activity_ratio > 1.0,
            "range_wake": range_ratio > 1.0,
            "path_wake": path_delta > 0.0,
        })
    return result
