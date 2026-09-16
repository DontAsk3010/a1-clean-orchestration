from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

FORMULAS = (
    "K01_BREAK_RETEST_REACCEL_HOLD",
    "K02_SHAKEOUT_RECLAIM_RETEST_CONTINUE",
    "K03_FLOW_LEAD_PERSIST_PRICE_CATCHUP",
    "K04_EFFORT_NO_PROGRESS_THEN_EFFICIENCY_FLIP",
    "K05_COMPRESSION_HIGHER_LOW_BREAK_RETEST",
    "K06_RISE_PULLBACK_BASE_REACCEL",
    "K07_SELL_EXHAUSTION_CONTROL_TRANSFER",
    "K08_WAKE_PULLBACK_SECOND_WAVE_HOLD",
)


@dataclass
class SequenceState:
    stage: int = 0
    memory: dict[str, Any] = field(default_factory=dict)


def _b(s: Mapping[str, Any], key: str) -> bool:
    return bool(s.get(key, False))


def _f(s: Mapping[str, Any], key: str) -> float | None:
    v = s.get(key)
    return None if v is None else float(v)


def _participation(s: Mapping[str, Any]) -> bool:
    return _b(s, "value_wake") or _b(s, "volume_wake") or _b(s, "flow_wake")


def _accepted_progress(s: Mapping[str, Any]) -> bool:
    return _b(s, "path_up") and _b(s, "accept")


def _control_transfer(s: Mapping[str, Any]) -> bool:
    return _b(s, "flow_wake") and (_b(s, "accept") or _b(s, "path_up"))


def _remember(st: SequenceState, **values: Any) -> None:
    st.memory.update(values)


def _reset(st: SequenceState) -> None:
    st.stage = 0
    st.memory.clear()


def advance(fid: str, st: SequenceState, s: Mapping[str, Any]) -> bool:
    """Advance one publication snapshot. Return True only when full causal sequence completes.

    This module intentionally introduces no numeric thresholds. It consumes the same primitive
    relative states already produced by V11 (same-clock baseline comparisons, path, acceptance,
    acceleration, and flow availability) and changes only their causal ordering/dependency.
    """
    path = _f(s, "path")

    if fid == "K01_BREAK_RETEST_REACCEL_HOLD":
        # participation -> accepted first wave -> explicit pullback/retest -> second wave -> hold
        if st.stage == 0 and _participation(s):
            st.stage = 1; _remember(st, wake_path=path); return False
        if st.stage == 1 and _accepted_progress(s):
            st.stage = 2; _remember(st, first_path=path); return False
        if st.stage == 2:
            first = st.memory.get("first_path"); wake = st.memory.get("wake_path")
            if path is not None and first is not None and path < float(first) and (wake is None or path >= float(wake)):
                st.stage = 3; _remember(st, retest_path=path); return False
            return False
        if st.stage == 3:
            first = st.memory.get("first_path")
            if _accepted_progress(s) and path is not None and first is not None and path > float(first):
                st.stage = 4; _remember(st, second_path=path); return False
            return False
        if st.stage == 4:
            second = st.memory.get("second_path")
            if _accepted_progress(s) and path is not None and second is not None and path >= float(second):
                return True
            return False

    if fid == "K02_SHAKEOUT_RECLAIM_RETEST_CONTINUE":
        # precondition flags are expected from cache/formula context; current-day event begins at selling failure.
        if st.stage == 0 and _b(s, "sell_response_weakens"):
            st.stage = 1; _remember(st, exhaustion_path=path); return False
        if st.stage == 1 and _control_transfer(s):
            st.stage = 2; return False
        if st.stage == 2 and _accepted_progress(s):
            st.stage = 3; _remember(st, reclaim_path=path); return False
        if st.stage == 3:
            reclaim = st.memory.get("reclaim_path")
            if path is not None and reclaim is not None and path < float(reclaim) and _b(s, "accept"):
                st.stage = 4; return False
            return False
        if st.stage == 4 and _accepted_progress(s):
            return True

    if fid == "K03_FLOW_LEAD_PERSIST_PRICE_CATCHUP":
        # flow must lead and persist before price catches up.
        if st.stage == 0 and _b(s, "flow_wake") and not _b(s, "path_up"):
            st.stage = 1; return False
        if st.stage == 1 and _b(s, "flow_wake") and not _b(s, "path_up"):
            st.stage = 2; return False
        if st.stage == 2 and _accepted_progress(s):
            st.stage = 3; _remember(st, response_path=path); return False
        if st.stage == 3:
            response = st.memory.get("response_path")
            if _b(s, "accept") and path is not None and response is not None and path >= float(response):
                return True
            return False

    if fid == "K04_EFFORT_NO_PROGRESS_THEN_EFFICIENCY_FLIP":
        # high effort is not bullish by itself; it must first fail to move price, persist, then convert.
        if st.stage == 0 and _participation(s) and not _b(s, "path_up"):
            st.stage = 1; return False
        if st.stage == 1 and _participation(s) and not _b(s, "path_up"):
            st.stage = 2; return False
        if st.stage == 2 and _accepted_progress(s):
            st.stage = 3; _remember(st, flip_path=path); return False
        if st.stage == 3:
            flip = st.memory.get("flip_path")
            if _accepted_progress(s) and path is not None and flip is not None and path >= float(flip):
                return True
            return False

    if fid == "K05_COMPRESSION_HIGHER_LOW_BREAK_RETEST":
        # compression/higher-low are prior-context gates; current sequence is wake -> break -> retest -> renew.
        if st.stage == 0 and _participation(s):
            st.stage = 1; return False
        if st.stage == 1 and _accepted_progress(s) and _b(s, "range_expand"):
            st.stage = 2; _remember(st, break_path=path); return False
        if st.stage == 2:
            br = st.memory.get("break_path")
            if path is not None and br is not None and path < float(br) and _b(s, "accept"):
                st.stage = 3; return False
            return False
        if st.stage == 3 and _accepted_progress(s):
            return True

    if fid == "K06_RISE_PULLBACK_BASE_REACCEL":
        # prior rise/pullback/base are prior-context gates; current participation must return then reaccelerate and hold.
        if st.stage == 0 and _participation(s):
            st.stage = 1; return False
        if st.stage == 1 and _b(s, "accel") and _accepted_progress(s):
            st.stage = 2; _remember(st, reaccel_path=path); return False
        if st.stage == 2:
            rp = st.memory.get("reaccel_path")
            if _accepted_progress(s) and path is not None and rp is not None and path >= float(rp):
                return True
            return False

    if fid == "K07_SELL_EXHAUSTION_CONTROL_TRANSFER":
        # seller pressure -> weaker downside -> low stabilization -> buy turn -> accepted price progress.
        if st.stage == 0 and _b(s, "sell_pressure_present"):
            st.stage = 1; return False
        if st.stage == 1 and _b(s, "sell_response_weakens"):
            st.stage = 2; return False
        if st.stage == 2 and _b(s, "low_stabilized"):
            st.stage = 3; return False
        if st.stage == 3 and _control_transfer(s):
            st.stage = 4; return False
        if st.stage == 4 and _accepted_progress(s):
            return True

    if fid == "K08_WAKE_PULLBACK_SECOND_WAVE_HOLD":
        # true two-wave sequence replacing V11 J08: wake -> impulse1 -> giveback -> wake2 -> impulse2 -> hold.
        if st.stage == 0 and _participation(s) and _b(s, "path_up"):
            st.stage = 1; _remember(st, wake_path=path); return False
        if st.stage == 1 and _accepted_progress(s):
            st.stage = 2; _remember(st, impulse1_path=path); return False
        if st.stage == 2:
            p1 = st.memory.get("impulse1_path"); wp = st.memory.get("wake_path")
            if path is not None and p1 is not None and path < float(p1) and (wp is None or path >= float(wp)):
                st.stage = 3; return False
            return False
        if st.stage == 3 and _participation(s) and _b(s, "accel"):
            st.stage = 4; return False
        if st.stage == 4:
            p1 = st.memory.get("impulse1_path")
            if _accepted_progress(s) and path is not None and p1 is not None and path > float(p1):
                st.stage = 5; _remember(st, impulse2_path=path); return False
            return False
        if st.stage == 5:
            p2 = st.memory.get("impulse2_path")
            if _accepted_progress(s) and path is not None and p2 is not None and path >= float(p2):
                return True
            return False

    return False
