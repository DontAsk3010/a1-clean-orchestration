from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import telegram_mg_multihypothesis_v8 as v8
from . import telegram_mg_multihypothesis_v8e as v8e
from .telegram_mg_behavior_topology_v2 import _net_return_pct, _observed_step


def _outcome_fast(
    bars: Sequence[Mapping[str, Any]], index: int, buy_fee: float, sell_fee: float
) -> dict[str, Any]:
    if index + 1 >= len(bars):
        return {"evaluable": False}
    step = _observed_step(bars, index)
    nxt = v8._finite(bars[index + 1].get("open"))
    if step is None or nxt is None or nxt <= 0:
        return {"evaluable": False}
    step = float(step)
    entry = float(nxt) + step

    max_high: float | None = None
    max_high_offset: int | None = None
    min_low: float | None = None
    min_low_offset: int | None = None
    min_low_through_peak: float | None = None
    first_positive: int | None = None
    final_close: float | None = None

    future_highs: list[float] = []
    future_lows: list[float] = []
    for offset, row in enumerate(bars[index + 1 :], start=1):
        high = v8._finite(row.get("high"))
        low = v8._finite(row.get("low"))
        close = v8._finite(row.get("close"))
        if high is None or low is None or close is None or high < low:
            return {"evaluable": False}
        high = float(high); low = float(low); final_close = float(close)
        future_highs.append(high); future_lows.append(low)
        if max_high is None or high > max_high:
            max_high = high; max_high_offset = offset
        if min_low is None or low < min_low:
            min_low = low; min_low_offset = offset
        executable_high = max(0.0, high - step)
        if first_positive is None and _net_return_pct(entry, executable_high, buy_fee, sell_fee) > 0.0:
            first_positive = offset

    if max_high is None or max_high_offset is None or min_low is None or min_low_offset is None or final_close is None:
        return {"evaluable": False}

    min_low_through_peak = min(future_lows[:max_high_offset])
    high_exit = max(0.0, max_high - step)
    eod_exit = max(0.0, final_close - step)
    mfe = _net_return_pct(entry, high_exit, buy_fee, sell_fee)
    mae = (min_low / entry - 1.0) * 100.0
    eod = _net_return_pct(entry, eod_exit, buy_fee, sell_fee)
    pre_peak_mae = (min_low_through_peak / entry - 1.0) * 100.0
    adverse_abs = abs(min(0.0, pre_peak_mae))
    reward_to_pre_peak_adverse = None if adverse_abs == 0.0 else mfe / adverse_abs

    return {
        "evaluable": True,
        "entry_proxy": entry,
        "step_proxy": step,
        "net_mfe_pct": mfe,
        "mae_pct": mae,
        "eod_net_pct": eod,
        "peak_offset_bars": max_high_offset,
        "first_positive_net_offset_bars": first_positive,
        "pre_peak_mae_pct": pre_peak_mae,
        "session_worst_mae_pct": mae,
        "session_worst_offset_bars": min_low_offset,
        "peak_before_session_worst": max_high_offset < min_low_offset,
        "reward_to_pre_peak_adverse": reward_to_pre_peak_adverse,
    }


def build_report(**kwargs: Any) -> dict[str, Any]:
    original = v8._outcome
    v8._outcome = _outcome_fast  # type: ignore[assignment]
    try:
        report = v8e.build_report(**kwargs)
    finally:
        v8._outcome = original  # type: ignore[assignment]
    report["schema"] = "A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8F_RESULT_V1"
    report["performance_optimization"]["outcome_path_single_pass"] = True
    report["performance_optimization"]["outcome_semantics_changed"] = False
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    p.add_argument("--min-unique-days", type=int, default=20)
    p.add_argument("--top-each", type=int, default=18)
    p.add_argument("--top-formulas", type=int, default=80)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
        min_unique_days=a.min_unique_days,
        top_each=a.top_each,
        top_formulas=a.top_formulas,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
