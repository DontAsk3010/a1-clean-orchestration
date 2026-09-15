from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Any, Mapping, Sequence

TRUE = "TRUE"
FALSE = "FALSE"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CandidateParams:
    """Research parameters, not accepted/final thresholds."""

    effort_lookback: int
    progress_lookback: int
    high_lookback: int
    recovery_lookback: int
    low_stabilization_bars: int
    early_checkpoint_bar: int
    late_lift_min_bar: int

    def validate(self) -> None:
        for name, value in self.__dict__.items():
            if int(value) < 1:
                raise ValueError(f"PARAM_MUST_BE_POSITIVE:{name}")
        if self.late_lift_min_bar <= self.early_checkpoint_bar:
            raise ValueError("LATE_LIFT_MUST_FOLLOW_EARLY_CHECKPOINT")


def _state(value: bool | None) -> str:
    if value is None:
        return UNKNOWN
    return TRUE if value else FALSE


def _float(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    return float(value)


def _prior(values: Sequence[float | None], index: int, lookback: int) -> list[float] | None:
    start = index - lookback
    if start < 0:
        return None
    out = values[start:index]
    if len(out) != lookback or any(value is None for value in out):
        return None
    return [float(value) for value in out if value is not None]


def derive_haka_haki(
    trade_value: float | None,
    nbss_value: float | None,
    *,
    availability_proven: bool,
    mechanism_eligible: bool,
) -> dict[str, Any]:
    """Apply the locked historical source-scoped HAKA/HAKI decomposition.

    Missing/unproven availability is UNKNOWN and is never silently changed to zero.
    """

    if not availability_proven or not mechanism_eligible or trade_value is None or nbss_value is None:
        return {
            "state": UNKNOWN,
            "haka_value_1m": None,
            "haki_value_1m": None,
            "reason": "FLOW_INPUT_UNAVAILABLE_OR_MECHANISM_INELIGIBLE",
        }
    trade_value = float(trade_value)
    nbss_value = float(nbss_value)
    return {
        "state": "AVAILABLE",
        "haka_value_1m": (trade_value + nbss_value) / 2.0,
        "haki_value_1m": (trade_value - nbss_value) / 2.0,
        "reason": None,
    }


def evaluate_intraday_candidates(
    bars: Sequence[Mapping[str, Any]], params: CandidateParams
) -> list[dict[str, Any]]:
    """Evaluate F01-F05 from information available through each bar only.

    Expected bar fields:
      trading_date, open, high, low, close, trade_value, nbss,
      flow_available (bool), mechanism_eligible (bool), session_eligible (bool),
      canonical_vwap (optional; None means unavailable).

    No future bar is read.  F05B remains UNKNOWN when canonical VWAP is absent.
    """

    params.validate()
    highs = [_float(row, "high") for row in bars]
    lows = [_float(row, "low") for row in bars]
    closes = [_float(row, "close") for row in bars]
    trade_values = [_float(row, "trade_value") for row in bars]

    out: list[dict[str, Any]] = []
    current_date: str | None = None
    session_open: float | None = None
    session_index = -1
    early_close: float | None = None
    last_session_new_low_index: int | None = None
    session_low: float | None = None

    for i, row in enumerate(bars):
        trading_date = str(row.get("trading_date") or "")
        session_eligible = bool(row.get("session_eligible", False))
        if trading_date != current_date:
            current_date = trading_date
            session_open = None
            session_index = -1
            early_close = None
            last_session_new_low_index = None
            session_low = None

        o = _float(row, "open")
        h = highs[i]
        l = lows[i]
        c = closes[i]
        tv = trade_values[i]
        vwap = _float(row, "canonical_vwap")

        if session_eligible:
            session_index += 1
            if session_open is None:
                session_open = o
            if session_index == params.early_checkpoint_bar - 1:
                early_close = c
            if l is not None and (session_low is None or l < session_low):
                session_low = l
                last_session_new_low_index = session_index

        flow = derive_haka_haki(
            tv,
            _float(row, "nbss"),
            availability_proven=bool(row.get("flow_available", False)),
            mechanism_eligible=bool(row.get("mechanism_eligible", False)),
        )

        f01a: bool | None = None
        f01b: bool | None = None
        f02a: bool | None = None
        f02b: bool | None = None
        if i > 0 and None not in (h, c, highs[i - 1], closes[i - 1]) and flow["state"] == "AVAILABLE":
            buy_effort = float(flow["haka_value_1m"]) > float(flow["haki_value_1m"])
            sell_effort = float(flow["haki_value_1m"]) > float(flow["haka_value_1m"])
            f01a = bool(buy_effort and h <= float(highs[i - 1]) and c <= float(closes[i - 1]))
            if l is not None and lows[i - 1] is not None:
                f02a = bool(sell_effort and c >= float(closes[i - 1]) and l >= float(lows[i - 1]))

            prior_highs = _prior(highs, i, params.progress_lookback)
            prior_closes = _prior(closes, i, params.progress_lookback)
            prior_effort = _prior(trade_values, i, params.effort_lookback)
            if prior_highs is not None and prior_closes is not None and prior_effort is not None and tv is not None:
                f01b = bool(
                    buy_effort
                    and h <= max(prior_highs)
                    and c <= max(prior_closes)
                    and tv > fmean(prior_effort)
                )

            prior_highs_2 = _prior(highs, i, params.high_lookback)
            if f02a is not None and vwap is not None and prior_highs_2 is not None:
                f02b = bool(f02a and c >= vwap and h > max(prior_highs_2))

        prior_highs = _prior(highs, i, params.high_lookback)
        new_high: bool | None = None
        if h is not None and prior_highs is not None:
            new_high = h > max(prior_highs)

        previous_high_age = out[-1]["measurements"]["high_age_bars"] if out and out[-1]["trading_date"] == trading_date else None
        if new_high is True:
            high_age: int | None = 0
        elif new_high is False and previous_high_age is not None:
            high_age = int(previous_high_age) + 1
        else:
            high_age = None

        f04a: bool | None = None
        f04b: bool | None = None
        if session_eligible and session_open is not None and early_close is not None and c is not None:
            early_established = early_close > session_open
            if session_index >= params.early_checkpoint_bar - 1:
                f04a = bool(early_established and c >= early_close)
            if session_index >= params.late_lift_min_bar - 1:
                f04b = bool((not early_established) and c > session_open)

        prior_weakness: bool | None = None
        low_stable: bool | None = None
        reclaim_open: bool | None = None
        renewed_high: bool | None = new_high
        f05a: bool | None = None
        f05b: bool | None = None
        if session_eligible and session_open is not None and c is not None:
            prior_close_window = _prior(closes, i, params.recovery_lookback)
            if prior_close_window is not None:
                prior_weakness = min(prior_close_window) < session_open
            if last_session_new_low_index is not None:
                low_stable = (session_index - last_session_new_low_index) >= params.low_stabilization_bars
            if i > 0 and closes[i - 1] is not None:
                reclaim_open = float(closes[i - 1]) <= session_open < c
            if None not in (prior_weakness, low_stable, reclaim_open, renewed_high):
                f05a = bool(prior_weakness and low_stable and reclaim_open and renewed_high)

            if vwap is not None and i > 0:
                prev_vwap = _float(bars[i - 1], "canonical_vwap")
                prev_close = closes[i - 1]
                if prev_vwap is not None and prev_close is not None and None not in (prior_weakness, low_stable, renewed_high):
                    reclaim_vwap = float(prev_close) <= prev_vwap and c > vwap
                    f05b = bool(prior_weakness and low_stable and reclaim_vwap and renewed_high)

        out.append(
            {
                "trading_date": trading_date,
                "index": i,
                "states": {
                    "F01A_BUY_STALL_BASIC": _state(f01a),
                    "F01B_BUY_STALL_STALE_HIGH_EFFORT": _state(f01b),
                    "F02A_SELL_RESILIENCE_BASIC": _state(f02a),
                    "F02B_SELL_RESILIENCE_ACCEPTANCE_RENEWAL": _state(f02b),
                    "F03A_NEW_HIGH_EVENT": _state(new_high),
                    "F04A_EARLY_STRENGTH_RETAINED": _state(f04a),
                    "F04B_LATE_LIFT": _state(f04b),
                    "F05A_SESSION_OPEN_RECOVERY": _state(f05a),
                    "F05B_CANONICAL_VWAP_RECOVERY": _state(f05b),
                },
                "measurements": {
                    "haka_value_1m": flow["haka_value_1m"],
                    "haki_value_1m": flow["haki_value_1m"],
                    "flow_state": flow["state"],
                    "high_age_bars": high_age,
                    "session_bar_index": session_index if session_eligible else None,
                    "session_open": session_open,
                    "early_checkpoint_close": early_close,
                },
            }
        )
    return out


def evaluate_progressive_h2_h1(
    sessions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """F06: assign current H context using completed H-2 and H-1 only."""

    out: list[dict[str, Any]] = []
    for i, current in enumerate(sessions):
        if i < 2:
            out.append(
                {
                    "trading_date": current.get("trading_date"),
                    "F06A_PRICE_PROGRESS": UNKNOWN,
                    "F06B_PRICE_ACTIVITY_PROGRESS": UNKNOWN,
                    "h2_date": None,
                    "h1_date": None,
                }
            )
            continue
        h2 = sessions[i - 2]
        h1 = sessions[i - 1]
        required = ("high", "low", "close")
        if any(h2.get(key) is None or h1.get(key) is None for key in required):
            price = None
        else:
            h2_range = float(h2["high"]) - float(h2["low"])
            h1_range = float(h1["high"]) - float(h1["low"])
            price = bool(
                float(h1["close"]) > float(h2["close"])
                and float(h1["high"]) > float(h2["high"])
                and h1_range > h2_range
            )
        activity: bool | None = None
        if price is not None and h2.get("activity") is not None and h1.get("activity") is not None:
            activity = bool(price and float(h1["activity"]) > float(h2["activity"]))
        out.append(
            {
                "trading_date": current.get("trading_date"),
                "F06A_PRICE_PROGRESS": _state(price),
                "F06B_PRICE_ACTIVITY_PROGRESS": _state(activity),
                "h2_date": h2.get("trading_date"),
                "h1_date": h1.get("trading_date"),
            }
        )
    return out
