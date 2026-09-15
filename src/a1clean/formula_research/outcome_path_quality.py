from __future__ import annotations

from typing import Any, Mapping, Sequence


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _net_return_pct(entry: float, exit_price: float, buy_fee_pct: float, sell_fee_pct: float) -> float:
    buy_cost = float(entry) * (1.0 + float(buy_fee_pct) / 100.0)
    sell_net = float(exit_price) * (1.0 - float(sell_fee_pct) / 100.0)
    return (sell_net / buy_cost - 1.0) * 100.0


def evaluate_outcome_path_quality(
    *,
    bars: Sequence[Mapping[str, Any]],
    signal_index: int,
    entry_proxy: float,
    step_proxy: float,
    buy_fee_pct: float,
    sell_fee_pct: float,
) -> dict[str, Any]:
    """Outcome-only path diagnostics for historical replay research.

    These fields are never eligible as live formula inputs. They describe the
    chronology after a causal signal/entry proxy so research can distinguish a
    clean favorable path from a late recovery after a deep adverse excursion.
    """
    if signal_index + 1 >= len(bars) or entry_proxy <= 0 or step_proxy < 0:
        return {"evaluable": False}

    future = bars[signal_index + 1 :]
    path: list[dict[str, float | int]] = []
    for offset, row in enumerate(future, start=1):
        high = _num(row.get("high"))
        low = _num(row.get("low"))
        close = _num(row.get("close"))
        if high is None or low is None or close is None or high < low:
            return {"evaluable": False}
        executable_high = max(0.0, high - step_proxy)
        executable_close = max(0.0, close - step_proxy)
        path.append(
            {
                "offset": offset,
                "net_high_pct": _net_return_pct(entry_proxy, executable_high, buy_fee_pct, sell_fee_pct),
                "raw_low_drawdown_pct": (low / entry_proxy - 1.0) * 100.0,
                "eod_if_exit_now_net_pct": _net_return_pct(entry_proxy, executable_close, buy_fee_pct, sell_fee_pct),
            }
        )

    if not path:
        return {"evaluable": False}

    peak = max(path, key=lambda row: float(row["net_high_pct"]))
    peak_offset = int(peak["offset"])
    through_peak = [row for row in path if int(row["offset"]) <= peak_offset]
    pre_peak_mae = min(float(row["raw_low_drawdown_pct"]) for row in through_peak)
    first_positive = next((int(row["offset"]) for row in path if float(row["net_high_pct"]) > 0.0), None)
    worst = min(path, key=lambda row: float(row["raw_low_drawdown_pct"]))
    worst_offset = int(worst["offset"])

    mfe = float(peak["net_high_pct"])
    eod = float(path[-1]["eod_if_exit_now_net_pct"])
    adverse_abs = abs(min(0.0, pre_peak_mae))
    reward_to_pre_peak_adverse = None if adverse_abs == 0.0 else mfe / adverse_abs

    return {
        "evaluable": True,
        "net_mfe_pct": mfe,
        "eod_net_pct": eod,
        "peak_offset_bars": peak_offset,
        "first_positive_net_offset_bars": first_positive,
        "pre_peak_mae_pct": pre_peak_mae,
        "session_worst_mae_pct": float(worst["raw_low_drawdown_pct"]),
        "session_worst_offset_bars": worst_offset,
        "peak_before_session_worst": peak_offset < worst_offset,
        "reward_to_pre_peak_adverse": reward_to_pre_peak_adverse,
    }
