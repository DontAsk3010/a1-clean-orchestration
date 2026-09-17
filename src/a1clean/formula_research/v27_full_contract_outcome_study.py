from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .durable_cache_catalog import governed_sources_from_durable_cache
from .haka_haki_reconstruction import DEC_2024_CONTRACT, reconstruct_bar

SCHEMA = "A1_V27_FULL_CONTRACT_OUTCOME_STUDY_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
MATRIX_SCHEMA = "A1_FULL_CONTRACT_OUTCOME_DOMAIN_MATRIX_V1"
ALLOWED_STATUSES = {
    "STUDIED_AVAILABLE_PROVEN",
    "UNAVAILABLE_IN_GOVERNED_SOURCE",
    "SEMANTICS_UNPROVEN",
    "NOT_CAUSALLY_TIMED",
    "NOT_APPLICABLE_WITH_REASON",
}
S = "STUDIED_AVAILABLE_PROVEN"
U = "UNAVAILABLE_IN_GOVERNED_SOURCE"
P = "SEMANTICS_UNPROVEN"
T = "NOT_CAUSALLY_TIMED"
N = "NOT_APPLICABLE_WITH_REASON"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canon_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def slug(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def pct(value: float | None, ref: float | None) -> float | None:
    if value is None or ref in (None, 0.0):
        return None
    return (value / ref - 1.0) * 100.0


def ratio(value: float | None, ref: float | None) -> float | None:
    if value is None or ref in (None, 0.0):
        return None
    return value / ref


def load_matrix(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema") != MATRIX_SCHEMA:
        raise RuntimeError("V27_DOMAIN_MATRIX_SCHEMA_MISMATCH")
    if obj.get("reserved_oos_untouched") is not True:
        raise RuntimeError("V27_DOMAIN_MATRIX_OOS_LOCK_MISSING")
    domains = list(obj.get("domains", []))
    ids = [str(x.get("id") or "") for x in domains]
    if not ids or any(not x for x in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("V27_DOMAIN_MATRIX_INVALID_IDS")
    enum = set(str(x) for x in obj.get("final_event_status_enum", []))
    if enum != ALLOWED_STATUSES:
        raise RuntimeError("V27_DOMAIN_MATRIX_STATUS_ENUM_MISMATCH")
    obj["domain_ids"] = ids
    obj["sha256"] = sha256_file(path)
    return obj


def grouped_jsonl_gz(path: Path) -> Iterable[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    current: tuple[str, str, str] | None = None
    group: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            key = (str(rec.get("source") or ""), str(rec.get("ticker") or ""), str(rec.get("date") or ""))
            if not all(key):
                raise RuntimeError(f"V27_BAD_EVENT_IDENTITY:{line_no}:{key}")
            if current is None:
                current = key
            elif key != current:
                yield current, group
                current, group = key, []
            group.append(rec)
    if current is not None:
        yield current, group


def cumulative_add(arr: list[float], value: float | None) -> None:
    arr.append(arr[-1] + (0.0 if value is None else value))


def cumulative_count(arr: list[int], condition: bool) -> None:
    arr.append(arr[-1] + int(condition))


def build_day_arrays(bars: Sequence[Mapping[str, Any]], *, allow_haka_haki: bool) -> dict[str, Any]:
    n = len(bars)
    prefix_high: list[float | None] = [None] * n
    prefix_low: list[float | None] = [None] * n
    volume_sum = [0.0]
    value_sum = [0.0]
    volume_count = [0]
    value_count = [0]
    zero_volume_count = [0]
    zero_value_count = [0]
    nbss_sum = [0.0]
    nbss_count = [0]
    haka_sum = [0.0]
    haki_sum = [0.0]
    hh_count = [0]
    ret_sum = [0.0]
    ret_sq_sum = [0.0]
    ret_abs_sum = [0.0]
    ret_count = [0]
    unchanged_count = [0]
    suffix_max_abs_ret: list[float | None] = [None] * (n + 1)
    timestamps: dict[str, int] = {}
    one_min_ret: list[float | None] = [None] * n
    cur_hi: float | None = None
    cur_lo: float | None = None
    prev_close: float | None = None

    for i, row in enumerate(bars):
        ts = str(row.get("timestamp") or "")
        if ts:
            timestamps[ts] = i
        hi = f(row.get("high")); lo = f(row.get("low")); close = f(row.get("close"))
        vol = f(row.get("volume")); val = f(row.get("trade_value"))
        if hi is not None:
            cur_hi = hi if cur_hi is None else max(cur_hi, hi)
        if lo is not None:
            cur_lo = lo if cur_lo is None else min(cur_lo, lo)
        prefix_high[i] = cur_hi; prefix_low[i] = cur_lo
        cumulative_add(volume_sum, vol); cumulative_add(value_sum, val)
        cumulative_count(volume_count, vol is not None); cumulative_count(value_count, val is not None)
        cumulative_count(zero_volume_count, vol == 0.0 if vol is not None else False)
        cumulative_count(zero_value_count, val == 0.0 if val is not None else False)

        flow_ok = bool(row.get("flow_available", False)) and bool(row.get("mechanism_eligible", False))
        nbss = f(row.get("nbss")) if flow_ok else None
        cumulative_add(nbss_sum, nbss); cumulative_count(nbss_count, nbss is not None)

        haka = haki = None
        if allow_haka_haki:
            rec = reconstruct_bar(row)
            haka = f(rec.get("haka")); haki = f(rec.get("haki"))
        cumulative_add(haka_sum, haka); cumulative_add(haki_sum, haki)
        cumulative_count(hh_count, haka is not None and haki is not None)

        r = pct(close, prev_close)
        one_min_ret[i] = r
        cumulative_add(ret_sum, r)
        cumulative_add(ret_sq_sum, None if r is None else r * r)
        cumulative_add(ret_abs_sum, None if r is None else abs(r))
        cumulative_count(ret_count, r is not None)
        cumulative_count(unchanged_count, r == 0.0 if r is not None else False)
        if close is not None:
            prev_close = close

    running: float | None = None
    for i in range(n - 1, -1, -1):
        r = one_min_ret[i]
        if r is not None:
            running = abs(r) if running is None else max(running, abs(r))
        suffix_max_abs_ret[i] = running

    return {
        "n": n,
        "prefix_high": prefix_high,
        "prefix_low": prefix_low,
        "volume_sum": volume_sum,
        "value_sum": value_sum,
        "volume_count": volume_count,
        "value_count": value_count,
        "zero_volume_count": zero_volume_count,
        "zero_value_count": zero_value_count,
        "nbss_sum": nbss_sum,
        "nbss_count": nbss_count,
        "haka_sum": haka_sum,
        "haki_sum": haki_sum,
        "hh_count": hh_count,
        "ret_sum": ret_sum,
        "ret_sq_sum": ret_sq_sum,
        "ret_abs_sum": ret_abs_sum,
        "ret_count": ret_count,
        "unchanged_count": unchanged_count,
        "suffix_max_abs_ret": suffix_max_abs_ret,
        "timestamps": timestamps,
    }


def range_sum(prefix: Sequence[float], start: int, end: int) -> float:
    if end < start:
        return 0.0
    return float(prefix[end + 1]) - float(prefix[start])


def range_count(prefix: Sequence[int], start: int, end: int) -> int:
    if end < start:
        return 0
    return int(prefix[end + 1]) - int(prefix[start])


def return_stats(arr: Mapping[str, Any], start: int, end: int) -> dict[str, Any]:
    if end < start:
        return {"n": 0, "mean_pct": None, "std_pct": None, "mean_abs_pct": None}
    n = range_count(arr["ret_count"], start, end)
    if n <= 0:
        return {"n": 0, "mean_pct": None, "std_pct": None, "mean_abs_pct": None}
    total = range_sum(arr["ret_sum"], start, end)
    sq = range_sum(arr["ret_sq_sum"], start, end)
    abs_total = range_sum(arr["ret_abs_sum"], start, end)
    mean = total / n
    var = max(0.0, sq / n - mean * mean)
    return {"n": n, "mean_pct": mean, "std_pct": math.sqrt(var), "mean_abs_pct": abs_total / n}


def daily_summary(bars: Sequence[Mapping[str, Any]], source: str) -> dict[str, Any]:
    if not bars:
        return {"source": source, "date": None, "bars": 0}
    opens = [f(x.get("open")) for x in bars]
    highs = [f(x.get("high")) for x in bars]
    lows = [f(x.get("low")) for x in bars]
    closes = [f(x.get("close")) for x in bars]
    vols = [f(x.get("volume")) for x in bars]
    vals = [f(x.get("trade_value")) for x in bars]
    flow = [f(x.get("nbss")) for x in bars if bool(x.get("flow_available", False)) and bool(x.get("mechanism_eligible", False)) and f(x.get("nbss")) is not None]
    op = next((x for x in opens if x is not None), None)
    cl = next((x for x in reversed(closes) if x is not None), None)
    hi = max((x for x in highs if x is not None), default=None)
    lo = min((x for x in lows if x is not None), default=None)
    return {
        "source": source,
        "date": str(bars[0].get("timestamp") or "")[:10] or None,
        "open": op,
        "high": hi,
        "low": lo,
        "close": cl,
        "return_pct": pct(cl, op),
        "range_pct": pct(hi, lo),
        "volume_sum": sum(x for x in vols if x is not None),
        "trade_value_sum": sum(x for x in vals if x is not None),
        "nbss_sum": sum(flow) if flow else None,
        "nbss_rows": len(flow),
        "bars": len(bars),
        "first_timestamp": str(bars[0].get("timestamp") or ""),
        "last_timestamp": str(bars[-1].get("timestamp") or ""),
    }


def load_history(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"last_by_ticker": {}, "current_market_date": None, "previous_market_date": None, "last_source": None}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        obj = json.load(fh)
    return obj


def save_history(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    tmp.replace(path)


def history_digest(state: Mapping[str, Any]) -> str:
    return canon_hash(state)


def source_gap_crosses_reserved(previous_source: str | None, source: str) -> bool:
    return previous_source == "Raw Feb 03-28-2025.csv" and source == "Raw April 01-30-2025.csv"


def update_market_date(state: dict[str, Any], *, source: str, current_date: str) -> None:
    active = state.get("current_market_date")
    if active is None:
        state["current_market_date"] = current_date
        state["previous_market_date"] = None
        state["last_source"] = source
        return
    if current_date == active:
        state["last_source"] = source
        return
    previous_source = str(state.get("last_source") or "") or None
    if source_gap_crosses_reserved(previous_source, source):
        state["previous_market_date"] = None
    else:
        state["previous_market_date"] = active
    state["current_market_date"] = current_date
    state["last_source"] = source


def static_statuses() -> dict[str, str]:
    return {
        "NFSS_FLOW": U,
        "BROKER_PARTICIPANT_GROSS_BUY_SELL_NET": U,
        "TICK_TIME_AND_TRADE": U,
        "DIRECT_LIQUIDITY_L1_BBO": U,
        "DIRECT_LIQUIDITY_L2_DEPTH_QUEUE": U,
        "FINANCIAL_ISSUER_CORPORATE_ACTION_CONTEXT": T,
        "MARKET_SECTOR_CONTEXT": T,
    }


def static_reasons() -> dict[str, str]:
    return {
        "NFSS_FLOW": "separate NFSS is not bound in the current governed V2.2 corpus",
        "BROKER_PARTICIPANT_GROSS_BUY_SELL_NET": "historical broker/participant gross buy-sell-net is not physically bound/proven in V2.2",
        "TICK_TIME_AND_TRADE": "historical tick/Time & Trade is not physically bound/proven in V2.2",
        "DIRECT_LIQUIDITY_L1_BBO": "historical L1/BBO is unavailable/not proven in the current governed corpus",
        "DIRECT_LIQUIDITY_L2_DEPTH_QUEUE": "historical L2/depth/order-book/queue is unavailable/not proven in the current governed corpus",
        "FINANCIAL_ISSUER_CORPORATE_ACTION_CONTEXT": "no authoritative causal known-at timestamp is bound to current V2.2 events",
        "MARKET_SECTOR_CONTEXT": "no exact causally timed market/sector series is bound to current V2.2 events",
    }


def event_measurements(
    event: Mapping[str, Any],
    *,
    bars: Sequence[Mapping[str, Any]],
    arr: Mapping[str, Any],
    prior: Mapping[str, Any] | None,
    previous_market_date: str | None,
    source: str,
    domain_ids: Sequence[str],
    allow_haka_haki: bool,
) -> dict[str, Any]:
    n = len(bars)
    di = int(event.get("detection_bar_index", -1))
    if di < 0 or di >= n:
        raise RuntimeError(f"V27_BAD_DETECTION_INDEX:{source}:{event.get('ticker')}:{event.get('date')}:{di}:{n}")
    row = bars[di]
    det_close = f(row.get("close")) or f(event.get("detection_close"))
    first_open = f(bars[0].get("open"))
    prefix_hi = arr["prefix_high"][di]
    prefix_lo = arr["prefix_low"][di]
    future_start = di + 1
    future_end = n - 1
    future_n = max(0, n - future_start)
    hi = f(event.get("future_max_high")); lo = f(event.get("future_min_low"))
    hi_ts = str(event.get("future_max_high_timestamp") or "") or None
    lo_ts = str(event.get("future_min_low_timestamp") or "") or None
    hi_i = arr["timestamps"].get(hi_ts) if hi_ts else None
    lo_i = arr["timestamps"].get(lo_ts) if lo_ts else None
    final_close = f(event.get("eod_close"))
    prev_close_1m = f(bars[di - 1].get("close")) if di > 0 else None
    prev_volume = f(bars[di - 1].get("volume")) if di > 0 else None
    prev_value = f(bars[di - 1].get("trade_value")) if di > 0 else None
    det_volume = f(row.get("volume")); det_value = f(row.get("trade_value"))
    prefix_vol_sum = range_sum(arr["volume_sum"], 0, di)
    prefix_val_sum = range_sum(arr["value_sum"], 0, di)
    prefix_vol_n = range_count(arr["volume_count"], 0, di)
    prefix_val_n = range_count(arr["value_count"], 0, di)
    future_vol_sum = range_sum(arr["volume_sum"], future_start, future_end)
    future_val_sum = range_sum(arr["value_sum"], future_start, future_end)
    future_vol_n = range_count(arr["volume_count"], future_start, future_end)
    future_val_n = range_count(arr["value_count"], future_start, future_end)
    prefix_nbss_sum = range_sum(arr["nbss_sum"], 0, di)
    prefix_nbss_n = range_count(arr["nbss_count"], 0, di)
    future_nbss_sum = range_sum(arr["nbss_sum"], future_start, future_end)
    future_nbss_n = range_count(arr["nbss_count"], future_start, future_end)
    flow_ok = bool(row.get("flow_available", False)) and bool(row.get("mechanism_eligible", False))
    det_nbss = f(row.get("nbss")) if flow_ok else None
    prefix_ret = return_stats(arr, 1, di)
    future_ret = return_stats(arr, future_start, future_end)
    prefix_range_pct = pct(prefix_hi, prefix_lo)
    future_range_pct = pct(hi, lo)
    det_bar_range_pct = pct(f(row.get("high")), f(row.get("low")))
    range_position = None
    if det_close is not None and prefix_hi is not None and prefix_lo is not None and prefix_hi > prefix_lo:
        range_position = (det_close - prefix_lo) / (prefix_hi - prefix_lo)

    prior_valid = prior is not None and previous_market_date is not None and str(prior.get("date")) == previous_market_date
    statuses = static_statuses()
    reasons = static_reasons()
    evidence: dict[str, Any] = {}

    if prior_valid:
        statuses["PRIOR_H1_CONTEXT"] = S
        evidence["PRIOR_H1_CONTEXT"] = dict(prior)
    else:
        statuses["PRIOR_H1_CONTEXT"] = U
        reasons["PRIOR_H1_CONTEXT"] = (
            "immediately previous governed market date is unavailable in this development corpus"
            if previous_market_date is None
            else "ticker has no governed source packet on the immediately previous governed market date"
        )

    statuses.update({
        "OPEN_GAP_CONTEXT": S,
        "INITIATION_QUALITY": S,
        "PRICE_OHLC_PATH": S,
        "HIGH_LOW_LIFECYCLE": S,
        "PULLBACK_DEFEND_RECLAIM": S,
        "MULTIBAR_PERSISTENCE_TIMING": S,
        "VOLUME_PARTICIPATION": S,
        "TRADE_VALUE_PARTICIPATION": S,
        "RANGE_VOLATILITY_DEVELOPMENT": S,
        "PROGRESS_RETENTION_GIVEBACK": S,
        "EXTENSION_REMAINING_ROOM": S,
        "TRADABILITY_FROM_BARS": S,
        "CONTRADICTION_FAILURE_INVALIDATION": S if future_n else N,
        "RECOVERY_REVERSAL_REACCELERATION": S if future_n else N,
        "OUTCOME_PATH_MFE_MAE_ORDERING": S if future_n else N,
        "CAUSAL_PROVENANCE_TIMING": S,
    })
    if not future_n:
        reasons["CONTRADICTION_FAILURE_INVALIDATION"] = "event is right-censored at final available session bar"
        reasons["RECOVERY_REVERSAL_REACCELERATION"] = "event is right-censored at final available session bar"
        reasons["OUTCOME_PATH_MFE_MAE_ORDERING"] = "event is right-censored at final available session bar"

    if prefix_nbss_n + future_nbss_n > 0:
        statuses["NBSS_FLOW"] = S
        statuses["EFFORT_PRICE_RESPONSE"] = S
    else:
        statuses["NBSS_FLOW"] = U
        statuses["EFFORT_PRICE_RESPONSE"] = U
        reasons["NBSS_FLOW"] = "no flow-available and mechanism-eligible NBSS evidence exists on this event journey"
        reasons["EFFORT_PRICE_RESPONSE"] = "flow effort-response cannot be measured where validated flow is unavailable"

    hh_n = range_count(arr["hh_count"], 0, future_end)
    if allow_haka_haki and hh_n > 0:
        statuses["HAKA_HAKI"] = S
    else:
        statuses["HAKA_HAKI"] = P
        reasons["HAKA_HAKI"] = "exact HAKA/HAKI reconstruction contract is not proven for this source/event"

    prior_close = f(prior.get("close")) if prior_valid and prior is not None else None
    evidence["OPEN_GAP_CONTEXT"] = {
        "session_open": first_open,
        "prior_close": prior_close,
        "gap_pct": pct(first_open, prior_close),
        "running_high_at_detection": prefix_hi,
        "running_low_at_detection": prefix_lo,
        "open_broken_before_or_at_detection": (prefix_lo < first_open) if prefix_lo is not None and first_open is not None else None,
        "open_is_running_low_at_detection": (prefix_lo == first_open) if prefix_lo is not None and first_open is not None else None,
    }
    evidence["INITIATION_QUALITY"] = {
        "detection_close": det_close,
        "previous_1m_close": prev_close_1m,
        "detection_1m_return_pct": pct(det_close, prev_close_1m),
        "open_to_detection_path_pct": pct(det_close, first_open),
        "detection_bar_range_pct": det_bar_range_pct,
        "prefix_return_stats": prefix_ret,
        "prefix_volume_per_bar": prefix_vol_sum / prefix_vol_n if prefix_vol_n else None,
        "prefix_value_per_bar": prefix_val_sum / prefix_val_n if prefix_val_n else None,
    }
    evidence["PRICE_OHLC_PATH"] = {
        "detection_bar": {k: f(row.get(k)) for k in ("open", "high", "low", "close")},
        "session_open": first_open,
        "running_high_at_detection": prefix_hi,
        "running_low_at_detection": prefix_lo,
        "future_max_high": hi,
        "future_min_low": lo,
        "eod_close": final_close,
        "mfe_pct_from_detection_close": f(event.get("mfe_pct_from_detection_close")),
        "mae_pct_from_detection_close": f(event.get("mae_pct_from_detection_close")),
        "eod_return_pct_from_detection_close": f(event.get("eod_return_pct_from_detection_close")),
        "future_price_sequence_sha256": str(event.get("future_state_sequence_sha256") or ""),
    }
    evidence["HIGH_LOW_LIFECYCLE"] = {
        "running_high_at_detection": prefix_hi,
        "running_low_at_detection": prefix_lo,
        "child_fresh_high": event.get("child_fresh_high"),
        "child_fresh_low": event.get("child_fresh_low"),
        "future_max_high": hi,
        "future_max_high_timestamp": hi_ts,
        "future_min_low": lo,
        "future_min_low_timestamp": lo_ts,
        "extreme_order": event.get("extreme_order"),
        "bars_to_future_high": (hi_i - di) if hi_i is not None else None,
        "bars_to_future_low": (lo_i - di) if lo_i is not None else None,
    }
    evidence["PULLBACK_DEFEND_RECLAIM"] = {
        "future_min_below_detection_close": (lo < det_close) if lo is not None and det_close is not None else None,
        "future_max_at_or_above_detection_close": (hi >= det_close) if hi is not None and det_close is not None else None,
        "pullback_then_recovered_above_detection_by_future_high": (
            lo_i is not None and hi_i is not None and lo_i < hi_i and lo is not None and det_close is not None and lo < det_close and hi is not None and hi >= det_close
        ),
        "open_defended_through_future_extreme": (lo >= first_open) if lo is not None and first_open is not None else None,
        "open_break_after_detection": (lo < first_open) if lo is not None and first_open is not None else None,
        "open_break_then_recovery_above_open": (
            lo_i is not None and hi_i is not None and lo_i < hi_i and lo is not None and first_open is not None and lo < first_open and hi is not None and hi >= first_open
        ),
        "future_reaches_or_exceeds_prefix_high": (hi >= prefix_hi) if hi is not None and prefix_hi is not None else None,
    }
    evidence["MULTIBAR_PERSISTENCE_TIMING"] = {
        "detection_timestamp": event.get("detection_timestamp"),
        "future_bar_count": int(event.get("future_bar_count", 0)),
        "future_run_count": int(event.get("future_run_count", 0)),
        "future_run_rows": int(event.get("future_run_rows", 0)),
        "first_later_state_times": event.get("first_later_state_times", {}),
        "final_state_start_timestamp": event.get("final_state_start_timestamp"),
        "eod_timestamp": event.get("eod_timestamp"),
    }
    evidence["VOLUME_PARTICIPATION"] = {
        "detection_volume": det_volume,
        "previous_1m_volume": prev_volume,
        "detection_volume_change": None if det_volume is None or prev_volume is None else det_volume - prev_volume,
        "prefix_volume_sum": prefix_vol_sum,
        "prefix_volume_per_bar": prefix_vol_sum / prefix_vol_n if prefix_vol_n else None,
        "future_volume_sum": future_vol_sum,
        "future_volume_per_bar": future_vol_sum / future_vol_n if future_vol_n else None,
        "prefix_zero_volume_rows": range_count(arr["zero_volume_count"], 0, di),
        "future_zero_volume_rows": range_count(arr["zero_volume_count"], future_start, future_end),
    }
    evidence["TRADE_VALUE_PARTICIPATION"] = {
        "detection_trade_value": det_value,
        "previous_1m_trade_value": prev_value,
        "detection_value_change": None if det_value is None or prev_value is None else det_value - prev_value,
        "prefix_trade_value_sum": prefix_val_sum,
        "prefix_value_per_bar": prefix_val_sum / prefix_val_n if prefix_val_n else None,
        "future_trade_value_sum": future_val_sum,
        "future_value_per_bar": future_val_sum / future_val_n if future_val_n else None,
        "prefix_zero_value_rows": range_count(arr["zero_value_count"], 0, di),
        "future_zero_value_rows": range_count(arr["zero_value_count"], future_start, future_end),
    }
    if statuses["EFFORT_PRICE_RESPONSE"] == S:
        evidence["EFFORT_PRICE_RESPONSE"] = {
            "detection_nbss": det_nbss,
            "child_relation": event.get("child_relation"),
            "child_flow_direction": event.get("child_flow_direction"),
            "child_flow_effort_change": event.get("child_flow_effort_change"),
            "prefix_nbss_sum": prefix_nbss_sum,
            "prefix_nbss_rows": prefix_nbss_n,
            "future_nbss_sum": future_nbss_sum,
            "future_nbss_rows": future_nbss_n,
            "first_later_state_times": event.get("first_later_state_times", {}),
        }
    evidence["RANGE_VOLATILITY_DEVELOPMENT"] = {
        "prefix_range_pct": prefix_range_pct,
        "detection_bar_range_pct": det_bar_range_pct,
        "future_extreme_range_pct": future_range_pct,
        "prefix_1m_return_stats": prefix_ret,
        "future_1m_return_stats": future_ret,
        "future_max_abs_1m_return_pct": arr["suffix_max_abs_ret"][future_start] if future_start < n else None,
    }
    mfe = f(event.get("mfe_pct_from_detection_close")); eod = f(event.get("eod_return_pct_from_detection_close"))
    evidence["PROGRESS_RETENTION_GIVEBACK"] = {
        "mfe_pct": mfe,
        "eod_return_pct": eod,
        "giveback_from_mfe_to_eod_pct": None if mfe is None or eod is None else mfe - eod,
        "extreme_order": event.get("extreme_order"),
        "future_max_high_timestamp": hi_ts,
        "future_min_low_timestamp": lo_ts,
    }
    evidence["EXTENSION_REMAINING_ROOM"] = {
        "open_to_detection_path_pct": pct(det_close, first_open),
        "detection_vs_prefix_high_pct": pct(det_close, prefix_hi),
        "detection_vs_prefix_low_pct": pct(det_close, prefix_lo),
        "detection_position_in_prefix_range_0_1": range_position,
        "later_mfe_pct_evaluation_only": mfe,
        "later_mae_pct_evaluation_only": f(event.get("mae_pct_from_detection_close")),
    }
    evidence["TRADABILITY_FROM_BARS"] = {
        "prefix_volume_per_bar": prefix_vol_sum / prefix_vol_n if prefix_vol_n else None,
        "prefix_value_per_bar": prefix_val_sum / prefix_val_n if prefix_val_n else None,
        "future_volume_per_bar": future_vol_sum / future_vol_n if future_vol_n else None,
        "future_value_per_bar": future_val_sum / future_val_n if future_val_n else None,
        "prefix_zero_volume_rows": range_count(arr["zero_volume_count"], 0, di),
        "prefix_zero_value_rows": range_count(arr["zero_value_count"], 0, di),
        "future_unchanged_close_rows": range_count(arr["unchanged_count"], future_start, future_end),
        "future_max_abs_1m_return_pct": arr["suffix_max_abs_ret"][future_start] if future_start < n else None,
        "direct_liquidity_claimed": False,
    }
    if statuses["NBSS_FLOW"] == S:
        evidence["NBSS_FLOW"] = {
            "detection_nbss": det_nbss,
            "prefix_nbss_sum": prefix_nbss_sum,
            "prefix_nbss_rows": prefix_nbss_n,
            "future_nbss_sum": future_nbss_sum,
            "future_nbss_rows": future_nbss_n,
            "flow_available_at_detection": flow_ok,
        }
    if statuses["HAKA_HAKI"] == S:
        evidence["HAKA_HAKI"] = {
            "prefix_haka_sum": range_sum(arr["haka_sum"], 0, di),
            "prefix_haki_sum": range_sum(arr["haki_sum"], 0, di),
            "future_haka_sum": range_sum(arr["haka_sum"], future_start, future_end),
            "future_haki_sum": range_sum(arr["haki_sum"], future_start, future_end),
            "proven_rows": hh_n,
            "child_haka_haki_dominance": event.get("child_haka_haki_dominance"),
            "source_contract": dict(DEC_2024_CONTRACT),
        }
    if future_n:
        evidence["CONTRADICTION_FAILURE_INVALIDATION"] = {
            "first_later_state_times": event.get("first_later_state_times", {}),
            "future_min_low": lo,
            "mae_pct": f(event.get("mae_pct_from_detection_close")),
            "eod_return_pct": eod,
            "final_state_token": event.get("final_state_token"),
        }
        evidence["RECOVERY_REVERSAL_REACCELERATION"] = {
            "first_later_state_times": event.get("first_later_state_times", {}),
            "extreme_order": event.get("extreme_order"),
            "future_max_high": hi,
            "future_min_low": lo,
            "mfe_pct": mfe,
            "mae_pct": f(event.get("mae_pct_from_detection_close")),
        }
        evidence["OUTCOME_PATH_MFE_MAE_ORDERING"] = {
            "mfe_pct": mfe,
            "mae_pct": f(event.get("mae_pct_from_detection_close")),
            "eod_return_pct": eod,
            "extreme_order": event.get("extreme_order"),
            "future_max_high_timestamp": hi_ts,
            "future_min_low_timestamp": lo_ts,
            "bars_to_future_high": (hi_i - di) if hi_i is not None else None,
            "bars_to_future_low": (lo_i - di) if lo_i is not None else None,
        }
    evidence["CAUSAL_PROVENANCE_TIMING"] = {
        "source": source,
        "ticker": event.get("ticker"),
        "date": event.get("date"),
        "detection_timestamp": event.get("detection_timestamp"),
        "detection_bar_index": di,
        "future_outcome_used_to_define_prefix_or_child": False,
    }

    if set(statuses) != set(domain_ids):
        missing = sorted(set(domain_ids) - set(statuses)); extra = sorted(set(statuses) - set(domain_ids))
        raise RuntimeError(f"V27_DOMAIN_COVERAGE_MISMATCH:missing={missing}:extra={extra}")
    if any(value not in ALLOWED_STATUSES for value in statuses.values()):
        raise RuntimeError("V27_INVALID_DOMAIN_STATUS")
    for did, status in statuses.items():
        if status == S and did not in evidence:
            raise RuntimeError(f"V27_STUDIED_DOMAIN_WITHOUT_EVIDENCE:{did}")
        if status != S and did not in reasons:
            reasons[did] = "domain not applicable/available/proven under current event-source contract"

    return {
        "coverage_status": statuses,
        "coverage_reason": reasons,
        "domain_evidence": evidence,
        "compact_metrics": {
            "prior_day_return_pct": f(prior.get("return_pct")) if prior_valid and prior is not None else None,
            "open_to_detection_path_pct": pct(det_close, first_open),
            "prefix_range_pct": prefix_range_pct,
            "prefix_volume_per_bar": prefix_vol_sum / prefix_vol_n if prefix_vol_n else None,
            "prefix_value_per_bar": prefix_val_sum / prefix_val_n if prefix_val_n else None,
            "prefix_nbss_sum": prefix_nbss_sum if prefix_nbss_n else None,
            "mfe_pct": mfe,
            "mae_pct": f(event.get("mae_pct_from_detection_close")),
            "eod_return_pct": eod,
            "giveback_from_mfe_to_eod_pct": None if mfe is None or eod is None else mfe - eod,
            "future_return_std_pct": f(future_ret.get("std_pct")),
            "future_mean_abs_return_pct": f(future_ret.get("mean_abs_pct")),
        },
    }


def metric_update(acc: dict[str, dict[str, float | int]], key: str, value: Any) -> None:
    x = f(value)
    if x is None:
        return
    row = acc.setdefault(key, {"n": 0, "sum": 0.0, "sum_sq": 0.0, "min": x, "max": x})
    row["n"] = int(row["n"]) + 1
    row["sum"] = float(row["sum"]) + x
    row["sum_sq"] = float(row["sum_sq"]) + x * x
    row["min"] = min(float(row["min"]), x)
    row["max"] = max(float(row["max"]), x)


def metric_finalize(row: Mapping[str, Any]) -> dict[str, Any]:
    n = int(row.get("n", 0))
    if n <= 0:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
    total = float(row["sum"]); sq = float(row["sum_sq"]); mean = total / n
    return {"n": n, "mean": mean, "std": math.sqrt(max(0.0, sq / n - mean * mean)), "min": float(row["min"]), "max": float(row["max"])}


def process_source(
    *,
    source: str,
    v26_root: Path,
    out_root: Path,
    matrix: Mapping[str, Any],
    v26_manifest: Mapping[str, Any],
    history_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sslug = slug(source)
    cp_dir = out_root / "checkpoints"; event_dir = out_root / "events"; history_dir = out_root / "history"
    for p in (cp_dir, event_dir, history_dir): p.mkdir(parents=True, exist_ok=True)
    cp_path = cp_dir / f"{sslug}.json"
    out_event = event_dir / f"{sslug}.jsonl.gz"
    history_path = history_dir / f"{sslug}.json.gz"
    input_event = v26_root / "events" / f"{sslug}.jsonl.gz"
    if not input_event.is_file():
        raise RuntimeError(f"V27_V26_EVENT_FILE_MISSING:{source}")
    expected_v26_sha = str(v26_manifest.get("outcome_evidence", {}).get("source_event_sha256", {}).get(source) or "")
    if not expected_v26_sha or sha256_file(input_event) != expected_v26_sha:
        raise RuntimeError(f"V27_V26_EVENT_DIGEST_MISMATCH:{source}")
    meta_path = v12r._meta_path(source); cache_path = v12r._cache_path(source)
    if not meta_path.is_file() or not cache_path.is_file():
        raise RuntimeError(f"V27_CACHE_MISSING:{source}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    before_digest = history_digest(history_state)
    fingerprint = canon_hash({
        "schema": SCHEMA,
        "source": source,
        "matrix_sha256": matrix["sha256"],
        "v26_event_sha256": expected_v26_sha,
        "cache_meta": meta,
        "history_before_sha256": before_digest,
    })
    if cp_path.is_file() and out_event.is_file() and history_path.is_file():
        try:
            old = json.loads(cp_path.read_text(encoding="utf-8"))
            if old.get("status") == "PASS" and old.get("fingerprint") == fingerprint and old.get("event_sha256") == sha256_file(out_event) and old.get("history_after_sha256") == sha256_file(history_path):
                reused_history = load_history(history_path)
                old = dict(old); old["reused_existing_pass"] = True
                return old, reused_history, {}
        except Exception:
            pass

    domain_ids = list(matrix["domain_ids"])
    event_iter = iter(grouped_jsonl_gz(input_event)); current_events = next(event_iter, None)
    tmp = out_event.with_suffix(out_event.suffix + ".tmp")
    event_count = 0; cache_ticker_days = 0; cache_rows = 0
    status_counts: dict[str, Counter[str]] = {did: Counter() for did in domain_ids}
    child_acc: dict[str, Any] = {}
    prefix_sources: dict[str, set[str]] = defaultdict(set)
    allow_hh = source == str(DEC_2024_CONTRACT["source_name"])

    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as out:
        for packet in v12r._iter_cached(source):
            ticker = str(packet.get("ticker") or ""); day = str(packet.get("date") or "")
            key = (source, ticker, day)
            bars = [dict(x) for x in packet.get("bars", [])]
            cache_ticker_days += 1; cache_rows += len(bars)
            update_market_date(history_state, source=source, current_date=day)
            previous_market_date = history_state.get("previous_market_date")
            prior = history_state.get("last_by_ticker", {}).get(ticker)

            if current_events is not None and current_events[0] == key:
                if not bars:
                    raise RuntimeError(f"V27_EVENT_ON_ZERO_SESSION:{key}")
                arr = build_day_arrays(bars, allow_haka_haki=allow_hh)
                for core in current_events[1]:
                    studied = event_measurements(
                        core,
                        bars=bars,
                        arr=arr,
                        prior=prior,
                        previous_market_date=previous_market_date,
                        source=source,
                        domain_ids=domain_ids,
                        allow_haka_haki=allow_hh,
                    )
                    rec = {
                        "schema": SCHEMA,
                        "source": source,
                        "block": core.get("block"),
                        "ticker": ticker,
                        "date": day,
                        "prefix_id": core.get("prefix_id"),
                        "child_id": core.get("child_id"),
                        "detection_timestamp": core.get("detection_timestamp"),
                        "core_v26": core,
                        **studied,
                        "future_outcome_rewrites_causal_state": False,
                    }
                    out.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                    event_count += 1
                    pid = str(core.get("prefix_id") or ""); cid = str(core.get("child_id") or "")
                    if not pid or not cid:
                        raise RuntimeError(f"V27_EMPTY_PREFIX_CHILD:{key}")
                    prefix_sources[pid].add(source)
                    c = child_acc.setdefault(cid, {"prefix_id": pid, "occurrences": 0, "sources": set(), "metrics": {}, "extreme_order": Counter()})
                    if c["prefix_id"] != pid:
                        raise RuntimeError(f"V27_CHILD_PREFIX_MISMATCH:{cid}")
                    c["occurrences"] += 1; c["sources"].add(source); c["extreme_order"][str(core.get("extreme_order") or "UNKNOWN")] += 1
                    for mk, mv in studied["compact_metrics"].items(): metric_update(c["metrics"], mk, mv)
                    for did, st in studied["coverage_status"].items(): status_counts[did][st] += 1
                current_events = next(event_iter, None)

            if bars:
                summary = daily_summary(bars, source)
                summary["date"] = day
                history_state.setdefault("last_by_ticker", {})[ticker] = summary

    if current_events is not None:
        raise RuntimeError(f"V27_UNCONSUMED_V26_EVENTS:{source}:{current_events[0]}")
    tmp.replace(out_event)
    save_history(history_path, history_state)
    cp = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "source": source,
        "fingerprint": fingerprint,
        "history_before_sha256": before_digest,
        "history_after_sha256": sha256_file(history_path),
        "ticker_days": cache_ticker_days,
        "minute_rows": cache_rows,
        "event_occurrences": event_count,
        "domain_status_counts": {did: dict(sorted(cnt.items())) for did, cnt in status_counts.items()},
        "event_sha256": sha256_file(out_event),
        "reused_existing_pass": False,
    }
    cp_path.write_text(json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8")
    return cp, history_state, {"children": child_acc, "prefix_sources": prefix_sources}


def merge_child_acc(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for cid, src in incoming.items():
        dst = target.setdefault(cid, {"prefix_id": src["prefix_id"], "occurrences": 0, "sources": set(), "metrics": {}, "extreme_order": Counter()})
        if dst["prefix_id"] != src["prefix_id"]:
            raise RuntimeError(f"V27_CHILD_PREFIX_GLOBAL_MISMATCH:{cid}")
        dst["occurrences"] += int(src["occurrences"]); dst["sources"].update(src["sources"]); dst["extreme_order"].update(src["extreme_order"])
        for mk, m in src["metrics"].items():
            d = dst["metrics"].setdefault(mk, {"n": 0, "sum": 0.0, "sum_sq": 0.0, "min": float(m["min"]), "max": float(m["max"])})
            d["n"] = int(d["n"]) + int(m["n"]); d["sum"] = float(d["sum"]) + float(m["sum"]); d["sum_sq"] = float(d["sum_sq"]) + float(m["sum_sq"])
            d["min"] = min(float(d["min"]), float(m["min"])); d["max"] = max(float(d["max"]), float(m["max"]))


def run(*, v26_root: Path, output_root: Path, matrix_path: Path, artifact_digest: str) -> dict[str, Any]:
    matrix = load_matrix(matrix_path)
    v26_manifest_path = v26_root / "manifest.json"
    if not v26_manifest_path.is_file():
        raise RuntimeError("V27_V26_MANIFEST_MISSING")
    v26 = json.loads(v26_manifest_path.read_text(encoding="utf-8"))
    if v26.get("status") != "PASS" or v26.get("reconciliation", {}).get("pass") is not True:
        raise RuntimeError("V27_V26_NOT_PASS")
    if v26.get("artifact_digest") != artifact_digest:
        raise RuntimeError("V27_ARTIFACT_DIGEST_MISMATCH")
    if v11.RESERVED_OOS in [str(x["source_name"]) for x in governed_sources_from_durable_cache()]:
        raise RuntimeError("V27_RESERVED_OOS_FORBIDDEN")

    output_root.mkdir(parents=True, exist_ok=True)
    governed = governed_sources_from_durable_cache(); sources = [str(x["source_name"]) for x in governed]
    history_state = {"last_by_ticker": {}, "current_market_date": None, "previous_market_date": None, "last_source": None}
    checkpoints: list[dict[str, Any]] = []
    global_children: dict[str, Any] = {}
    prefix_sources: dict[str, set[str]] = defaultdict(set)

    for source in sources:
        cp, history_state, extras = process_source(source=source, v26_root=v26_root, out_root=output_root, matrix=matrix, v26_manifest=v26, history_state=history_state)
        checkpoints.append(cp)
        if extras:
            merge_child_acc(global_children, extras["children"])
            for pid, ss in extras["prefix_sources"].items(): prefix_sources[pid].update(ss)
        elif cp.get("reused_existing_pass"):
            # Rebuild compact global summaries from durable V2.7 events without touching cache.
            path = output_root / "events" / f"{slug(source)}.jsonl.gz"
            local: dict[str, Any] = {}
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip(): continue
                    rec = json.loads(line); cid = str(rec["child_id"]); pid = str(rec["prefix_id"])
                    prefix_sources[pid].add(source)
                    c = local.setdefault(cid, {"prefix_id": pid, "occurrences": 0, "sources": set(), "metrics": {}, "extreme_order": Counter()})
                    c["occurrences"] += 1; c["sources"].add(source); c["extreme_order"][str(rec.get("core_v26", {}).get("extreme_order") or "UNKNOWN")] += 1
                    for mk, mv in rec.get("compact_metrics", {}).items(): metric_update(c["metrics"], mk, mv)
            merge_child_acc(global_children, local)

    child_path = output_root / "child-contract-summary.jsonl.gz"
    prefix_children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with gzip.open(child_path, "wt", encoding="utf-8", newline="\n") as fh:
        for cid in sorted(global_children):
            c = global_children[cid]
            metrics = {mk: metric_finalize(m) for mk, m in sorted(c["metrics"].items())}
            rec = {"child_id": cid, "prefix_id": c["prefix_id"], "occurrences": int(c["occurrences"]), "sources": sorted(c["sources"]), "source_count": len(c["sources"]), "extreme_order_counts": dict(sorted(c["extreme_order"].items())), "metrics": metrics}
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
            prefix_children[str(c["prefix_id"])].append(rec)

    prefix_path = output_root / "prefix-near-twin-full-contract-contrast.jsonl.gz"
    with gzip.open(prefix_path, "wt", encoding="utf-8", newline="\n") as fh:
        for pid in sorted(prefix_children):
            children = prefix_children[pid]
            metric_names = sorted({mk for c in children for mk in c["metrics"]})
            spans: dict[str, Any] = {}
            for mk in metric_names:
                means = [(c["child_id"], c["metrics"][mk]["mean"]) for c in children if c["metrics"].get(mk, {}).get("mean") is not None]
                if means:
                    vals = [float(x[1]) for x in means]
                    spans[mk] = {"child_means_available": len(means), "min_child_mean": min(vals), "max_child_mean": max(vals), "child_mean_span": max(vals) - min(vals)}
            rec = {"prefix_id": pid, "child_count": len(children), "event_occurrences": sum(int(c["occurrences"]) for c in children), "source_count": len(prefix_sources.get(pid, set())), "children": [c["child_id"] for c in children], "metric_child_mean_spans": spans, "winner_failure_label_assigned": False, "arbitrary_threshold_added": False}
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")

    total_events = sum(int(cp["event_occurrences"]) for cp in checkpoints)
    expected_events = int(v26["reconciliation"]["divergent_event_occurrences"])
    expected_children = int(v26["reconciliation"]["divergent_child_motifs_observed"])
    expected_prefixes = int(v26["reconciliation"]["divergent_prefixes_observed"])
    status_totals: dict[str, Counter[str]] = {did: Counter() for did in matrix["domain_ids"]}
    for cp in checkpoints:
        for did, counts in cp["domain_status_counts"].items(): status_totals[did].update({str(k): int(v) for k, v in counts.items()})
    domain_complete = all(sum(cnt.values()) == total_events and set(cnt).issubset(ALLOWED_STATUSES) for cnt in status_totals.values())
    ok = (
        len(checkpoints) == len(sources)
        and all(cp.get("status") == "PASS" for cp in checkpoints)
        and total_events == expected_events
        and len(global_children) == expected_children
        and len(prefix_children) == expected_prefixes
        and domain_complete
    )
    result = {
        "schema": SCHEMA,
        "status": "PASS" if ok else "FAIL",
        "research_status": STATUS,
        "artifact_digest": artifact_digest,
        "input_v26_manifest_sha256": sha256_file(v26_manifest_path),
        "domain_matrix_sha256": matrix["sha256"],
        "contract": {
            "v26_core_is_not_full_contract_completion": True,
            "all_original_contract_domains_required": True,
            "price_and_all_applicable_formation_context_read_together": True,
            "raw_reread": False,
            "census_rerun": False,
            "v22_remining": False,
            "reads_existing_normalized_tf1m_cache_once_per_source_for_new_full_contract_measurements": True,
            "future_outcome_is_evaluation_only": True,
            "missing_never_zero": True,
            "direct_liquidity_not_inferred_from_bar_tradability": True,
            "arbitrary_thresholds_added": False,
            "reserved_oos_untouched": True,
        },
        "reconciliation": {
            "sources": len(checkpoints), "expected_sources": len(sources),
            "event_occurrences": total_events, "expected_event_occurrences": expected_events,
            "divergent_child_motifs": len(global_children), "expected_divergent_child_motifs": expected_children,
            "divergent_prefixes": len(prefix_children), "expected_divergent_prefixes": expected_prefixes,
            "required_domains": len(matrix["domain_ids"]),
            "every_domain_accounted_for_every_event": domain_complete,
            "pass": ok,
        },
        "domain_status_totals": {did: dict(sorted(cnt.items())) for did, cnt in status_totals.items()},
        "outputs": {
            "child_contract_summary": str(child_path), "child_contract_summary_sha256": sha256_file(child_path),
            "prefix_near_twin_contrast": str(prefix_path), "prefix_near_twin_contrast_sha256": sha256_file(prefix_path),
            "event_files": len(checkpoints),
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not ok:
        raise RuntimeError("V27_FULL_CONTRACT_RECONCILIATION_FAILED")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--v26-root", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--matrix", required=True)
    p.add_argument("--artifact-digest", required=True)
    a = p.parse_args()
    result = run(v26_root=Path(a.v26_root), output_root=Path(a.output_root), matrix_path=Path(a.matrix), artifact_digest=a.artifact_digest)
    print(json.dumps({"schema": result["schema"], "status": result["status"], "reconciliation": result["reconciliation"], "outputs": result["outputs"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
