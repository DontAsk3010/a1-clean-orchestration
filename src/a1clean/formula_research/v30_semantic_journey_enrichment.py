from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import telegram_mg_structure_v12_runner as v12r
from .durable_cache_catalog import governed_sources_from_durable_cache
from .haka_haki_reconstruction import DEC_2024_CONTRACT, reconstruct_bar
from .minute_behavior_census_v21 import _f, _flow_price_relation, _pct, _sign

SCHEMA = "A1_V30_SEMANTIC_JOURNEY_ENRICHMENT_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
ROOT_V22_DIGEST = "deaacecc936174f66c9cd2138cbdcfb5c2120ad0ae8f0d4da8c4d7fed6484214"
EXPECTED_TICKER_DAYS = 298_483
EXPECTED_MINUTE_ROWS = 32_350_174
EXPECTED_ZERO_SESSION = 13_074


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest_obj(obj: Any) -> str:
    return hashlib.sha256(_canon(obj)).hexdigest()


def _slug(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _cmp(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "UNKNOWN"
    if cur > prev:
        return "UP"
    if cur < prev:
        return "DOWN"
    return "FLAT"


def _cmp_abs(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "UNKNOWN"
    return _cmp(abs(cur), abs(prev)).replace("UP", "ACCEL").replace("DOWN", "DECEL")


def _activity_change(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "UNKNOWN"
    if cur > prev:
        return "ACCEL"
    if cur < prev:
        return "DECEL"
    return "FLAT"


def _flow_dir(nbss: float | None, ok: bool) -> str:
    if not ok or nbss is None:
        return "UNKNOWN"
    if nbss > 0:
        return "BUY"
    if nbss < 0:
        return "SELL"
    return "NEUTRAL"


def _hh_dom(haka: float | None, haki: float | None) -> str:
    if haka is None or haki is None:
        return "UNKNOWN"
    if haka > haki:
        return "HAKA"
    if haki > haka:
        return "HAKI"
    return "BALANCED"


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    out = _f(value)
    return float(out) if out is not None and math.isfinite(float(out)) else None


def _state_key(state: Mapping[str, Any]) -> str:
    fields = (
        "price_direction",
        "volume_direction",
        "value_direction",
        "flow_direction",
        "flow_effort_change",
        "value_activity_change",
        "bar_range_change",
        "flow_price_relation",
        "fresh_high",
        "fresh_low",
        "open_state",
        "haka_haki_dominance",
    )
    return "|".join(f"{k}={state.get(k)}" for k in fields)


def _write_gz_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def _journey_resolution(
    bars: Sequence[Mapping[str, Any]],
    *,
    start_index: int,
    start_close: float | None,
    pre_start_running_high: float | None,
    pre_start_running_low: float | None,
    kind: str,
) -> dict[str, Any]:
    """Hindsight-only resolution. Never used to construct the causal state."""
    if start_index >= len(bars) - 1:
        return {
            "resolution_status": "OPEN_RIGHT_CENSORED",
            "resolution_timestamp": None,
            "resolution_index": None,
            "right_censored": True,
        }
    for j in range(start_index + 1, len(bars)):
        row = bars[j]
        ts = str(row.get("timestamp") or "")
        hi = _safe_float(row.get("high"))
        lo = _safe_float(row.get("low"))
        close = _safe_float(row.get("close"))
        if kind == "RECOVERY":
            if pre_start_running_high is not None and hi is not None and hi > pre_start_running_high:
                return {
                    "resolution_status": "RECOVERY_EXTENDED_TO_NEW_PRESTART_RUNNING_HIGH",
                    "resolution_timestamp": ts,
                    "resolution_index": j,
                    "right_censored": False,
                }
            if start_close is not None and close is not None and close < start_close:
                return {
                    "resolution_status": "FAILED_BELOW_RECOVERY_START_CLOSE",
                    "resolution_timestamp": ts,
                    "resolution_index": j,
                    "right_censored": False,
                }
        elif kind == "PULLBACK":
            if start_close is not None and close is not None and close >= start_close:
                return {
                    "resolution_status": "PULLBACK_START_CLOSE_RECLAIMED",
                    "resolution_timestamp": ts,
                    "resolution_index": j,
                    "right_censored": False,
                }
            if pre_start_running_low is not None and lo is not None and lo < pre_start_running_low:
                return {
                    "resolution_status": "PULLBACK_EXTENDED_TO_NEW_PRESTART_RUNNING_LOW",
                    "resolution_timestamp": ts,
                    "resolution_index": j,
                    "right_censored": False,
                }
    return {
        "resolution_status": "OPEN_RIGHT_CENSORED",
        "resolution_timestamp": None,
        "resolution_index": None,
        "right_censored": True,
    }


def enrich_ticker_day(
    bars: Sequence[Mapping[str, Any]],
    *,
    source: str,
    source_identity: Mapping[str, Any],
    ticker: str,
    trading_date: str,
    carry_in: Mapping[str, Any] | None,
    previous_governed_date: str | None,
    allow_haka_haki: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    base_identity = {
        "source": source,
        "source_drive_id": source_identity.get("source_drive_id"),
        "source_sha256": source_identity.get("source_sha256"),
        "generation_id": source_identity.get("generation_id"),
        "semantic_manifest_fingerprint": source_identity.get("semantic_manifest_fingerprint"),
        "ticker": ticker,
        "date": trading_date,
    }
    availability = {
        "participant_broker_flow": "UNKNOWN_UNPROVEN",
        "tick_time_and_trade": "UNAVAILABLE_UNPROVEN",
        "l1_bbo": "UNAVAILABLE_UNPROVEN",
        "l2_depth_orderbook_queue": "UNAVAILABLE_UNPROVEN",
        "financial_issuer_context": "NOT_CAUSALLY_BOUND_HERE",
        "market_sector_context": "NOT_CAUSALLY_BOUND_HERE",
        "haka_haki": "SOURCE_BOUND_PROVEN" if allow_haka_haki else "SEMANTICS_UNPROVEN_FOR_SOURCE",
    }

    if not bars:
        day = {
            **base_identity,
            "schema": SCHEMA,
            "status": STATUS,
            "zero_session_eligible": True,
            "bar_count": 0,
            "first_timestamp": None,
            "last_timestamp": None,
            "no_forced_event": True,
            "formation_run_count": 0,
            "semantic_marker_count": 0,
            "event_journey_count": 0,
            "open_right_censored_journey_count": 0,
            "carry_in": carry_in,
            "previous_governed_date": previous_governed_date,
            "availability": availability,
            "causal_view_separate_from_hindsight": True,
        }
        return day, [], []

    session_open = _safe_float(bars[0].get("open"))
    prev_close: float | None = None
    prev_volume: float | None = None
    prev_value: float | None = None
    prev_nbss: float | None = None
    prev_range: float | None = None
    prev_price_dir: str | None = None
    prev_flow_dir: str | None = None
    prev_hh: str | None = None
    run_hi: float | None = None
    run_lo: float | None = None
    open_broken = False
    markers: list[dict[str, Any]] = []
    journeys: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    active_run: dict[str, Any] | None = None
    state_history: list[dict[str, Any]] = []
    first_open_break_index: int | None = None
    open_reclaimed = False
    open_buy_nonresponse: dict[str, Any] | None = None
    open_sell_resilience: dict[str, Any] | None = None
    gap_markers = 0

    def add_marker(kind: str, i: int, ts: str, **extra: Any) -> None:
        markers.append({**base_identity, "kind": kind, "index": i, "timestamp": ts, **extra})

    for i, raw in enumerate(bars):
        ts = str(raw.get("timestamp") or "")
        op = _safe_float(raw.get("open")); hi = _safe_float(raw.get("high")); lo = _safe_float(raw.get("low")); close = _safe_float(raw.get("close"))
        volume = _safe_float(raw.get("volume")); value = _safe_float(raw.get("trade_value"))
        current_range = None if hi is None or lo is None else hi - lo
        old_hi, old_lo = run_hi, run_lo
        if hi is not None:
            run_hi = hi if run_hi is None else max(run_hi, hi)
        if lo is not None:
            run_lo = lo if run_lo is None else min(run_lo, lo)
        fresh_high = hi is not None and (old_hi is None or hi > old_hi)
        fresh_low = lo is not None and (old_lo is None or lo < old_lo)

        price_delta_pct = _pct(close, prev_close) if prev_close not in (None, 0) else None
        price_dir = _sign(price_delta_pct)
        volume_dir = _cmp(volume, prev_volume)
        value_dir = _cmp(value, prev_value)
        value_activity = _activity_change(value, prev_value)
        range_change = _cmp(current_range, prev_range)
        flow_ok = bool(raw.get("flow_available", False)) and bool(raw.get("mechanism_eligible", False))
        nbss = _safe_float(raw.get("nbss")) if flow_ok else None
        flow_dir = _flow_dir(nbss, flow_ok)
        flow_effort = _cmp_abs(nbss, prev_nbss) if flow_ok else "UNKNOWN"
        relation = _flow_price_relation(nbss, price_delta_pct, flow_ok)

        haka = haki = None
        hh = "UNKNOWN"
        if allow_haka_haki:
            rec = reconstruct_bar(raw)
            haka = _safe_float(rec.get("haka")); haki = _safe_float(rec.get("haki")); hh = _hh_dom(haka, haki)

        if session_open is not None and run_lo is not None and run_lo < session_open:
            open_broken = True
        if not open_broken:
            open_state = "DEFENDED_NOT_YET_BROKEN"
        elif close is not None and session_open is not None and close >= session_open:
            open_state = "RECLAIMED_AFTER_BREAK"
        else:
            open_state = "BELOW_AFTER_BREAK"

        state = {
            "price_direction": price_dir,
            "volume_direction": volume_dir,
            "value_direction": value_dir,
            "flow_direction": flow_dir,
            "flow_effort_change": flow_effort,
            "value_activity_change": value_activity,
            "bar_range_change": range_change,
            "flow_price_relation": relation,
            "fresh_high": fresh_high,
            "fresh_low": fresh_low,
            "open_state": open_state,
            "haka_haki_dominance": hh,
        }
        key = _state_key(state)
        state_history.append({"index": i, "timestamp": ts, "close": close, "pre_running_high": old_hi, "pre_running_low": old_lo, "state": state})

        if active_run is None or active_run["state_key"] != key:
            if active_run is not None:
                runs.append(active_run)
            active_run = {
                **base_identity,
                "schema": SCHEMA,
                "state_key": key,
                "state": state,
                "start_index": i,
                "end_index": i,
                "start_timestamp": ts,
                "end_timestamp": ts,
                "row_count": 1,
                "start_close": close,
                "end_close": close,
                "causal_only": True,
            }
        else:
            active_run["end_index"] = i
            active_run["end_timestamp"] = ts
            active_run["end_close"] = close
            active_run["row_count"] = int(active_run["row_count"]) + 1

        if i == 0:
            add_marker("SESSION_START", i, ts, session_open=session_open)
        if fresh_high:
            add_marker("FRESH_HIGH", i, ts, high=hi, prior_running_high=old_hi)
        if fresh_low:
            add_marker("FRESH_LOW", i, ts, low=lo, prior_running_low=old_lo)
        if first_open_break_index is None and session_open is not None and lo is not None and lo < session_open:
            first_open_break_index = i
            add_marker("OPEN_BREAK", i, ts, session_open=session_open, low=lo)
        if first_open_break_index is not None and not open_reclaimed and i > first_open_break_index and close is not None and session_open is not None and close >= session_open:
            open_reclaimed = True
            add_marker("OPEN_RECLAIM", i, ts, session_open=session_open, close=close, open_break_index=first_open_break_index)
        if prev_price_dir in {"UP", "DOWN"} and price_dir in {"UP", "DOWN"} and price_dir != prev_price_dir:
            add_marker("PRICE_REVERSAL", i, ts, from_direction=prev_price_dir, to_direction=price_dir)
            kind = "RECOVERY" if prev_price_dir == "DOWN" and price_dir == "UP" else "PULLBACK"
            resolution = _journey_resolution(
                bars,
                start_index=i,
                start_close=close,
                pre_start_running_high=old_hi,
                pre_start_running_low=old_lo,
                kind=kind,
            )
            journeys.append({
                **base_identity,
                "schema": SCHEMA,
                "journey_kind": kind,
                "causal_start": {"index": i, "timestamp": ts, "close": close, "known_at": ts},
                "hindsight_resolution": resolution,
                "future_resolution_not_used_to_define_start": True,
            })
        if prev_flow_dir in {"BUY", "SELL"} and flow_dir in {"BUY", "SELL"} and flow_dir != prev_flow_dir:
            add_marker("FLOW_DOMINANCE_CHANGE", i, ts, from_direction=prev_flow_dir, to_direction=flow_dir)
        if prev_hh in {"HAKA", "HAKI"} and hh in {"HAKA", "HAKI"} and hh != prev_hh:
            add_marker("HAKA_HAKI_DOMINANCE_CHANGE", i, ts, from_dominance=prev_hh, to_dominance=hh)

        if relation == "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE":
            if open_buy_nonresponse is None:
                open_buy_nonresponse = {"index": i, "timestamp": ts, "close": close}
                add_marker("BUY_NONRESPONSE_START", i, ts, close=close)
        elif open_buy_nonresponse is not None:
            if relation == "BUY_FLOW_PRICE_ADVANCE":
                add_marker("BUY_NONRESPONSE_TO_ADVANCE", i, ts, start_timestamp=open_buy_nonresponse["timestamp"], close=close)
                journeys.append({
                    **base_identity,
                    "schema": SCHEMA,
                    "journey_kind": "BUY_NONRESPONSE_WINDOW",
                    "causal_start": open_buy_nonresponse,
                    "hindsight_resolution": {"resolution_status": "BUY_FLOW_PRICE_ADVANCE", "resolution_index": i, "resolution_timestamp": ts, "right_censored": False},
                    "future_resolution_not_used_to_define_start": True,
                })
                open_buy_nonresponse = None
            elif flow_dir != "BUY":
                journeys.append({
                    **base_identity,
                    "schema": SCHEMA,
                    "journey_kind": "BUY_NONRESPONSE_WINDOW",
                    "causal_start": open_buy_nonresponse,
                    "hindsight_resolution": {"resolution_status": "FLOW_LEFT_BUY_BEFORE_ADVANCE", "resolution_index": i, "resolution_timestamp": ts, "right_censored": False},
                    "future_resolution_not_used_to_define_start": True,
                })
                open_buy_nonresponse = None

        if relation == "SELL_FLOW_PRICE_RESILIENCE":
            if open_sell_resilience is None:
                open_sell_resilience = {"index": i, "timestamp": ts, "close": close}
                add_marker("SELL_RESILIENCE_START", i, ts, close=close)
        elif open_sell_resilience is not None:
            if relation == "SELL_FLOW_PRICE_DECLINE":
                add_marker("SELL_RESILIENCE_TO_DECLINE", i, ts, start_timestamp=open_sell_resilience["timestamp"], close=close)
                journeys.append({
                    **base_identity,
                    "schema": SCHEMA,
                    "journey_kind": "SELL_RESILIENCE_WINDOW",
                    "causal_start": open_sell_resilience,
                    "hindsight_resolution": {"resolution_status": "SELL_FLOW_PRICE_DECLINE", "resolution_index": i, "resolution_timestamp": ts, "right_censored": False},
                    "future_resolution_not_used_to_define_start": True,
                })
                open_sell_resilience = None
            elif flow_dir != "SELL":
                journeys.append({
                    **base_identity,
                    "schema": SCHEMA,
                    "journey_kind": "SELL_RESILIENCE_WINDOW",
                    "causal_start": open_sell_resilience,
                    "hindsight_resolution": {"resolution_status": "FLOW_LEFT_SELL_BEFORE_DECLINE", "resolution_index": i, "resolution_timestamp": ts, "right_censored": False},
                    "future_resolution_not_used_to_define_start": True,
                })
                open_sell_resilience = None

        if i > 0:
            p = _parse_ts(str(bars[i - 1].get("timestamp") or "")); c = _parse_ts(ts)
            if p is not None and c is not None:
                delta = (c - p).total_seconds()
                if delta != 60.0:
                    gap_markers += 1
                    add_marker(
                        "TIMESTAMP_DISCONTINUITY_UNRESOLVED_SESSION_OR_SOURCE_GAP",
                        i,
                        ts,
                        previous_timestamp=str(bars[i - 1].get("timestamp") or ""),
                        delta_seconds=delta,
                        uncertainty="SESSION_RECESS_OR_SOURCE_GAP_NOT_INFERRED",
                    )

        if close is not None:
            prev_close = close
        if volume is not None:
            prev_volume = volume
        if value is not None:
            prev_value = value
        if flow_ok and nbss is not None:
            prev_nbss = nbss
        if current_range is not None:
            prev_range = current_range
        prev_price_dir = price_dir
        prev_flow_dir = flow_dir
        if hh != "UNKNOWN":
            prev_hh = hh

    if active_run is not None:
        runs.append(active_run)

    last_ts = str(bars[-1].get("timestamp") or "")
    if first_open_break_index is not None:
        journeys.append({
            **base_identity,
            "schema": SCHEMA,
            "journey_kind": "OPEN_BREAK_RECLAIM",
            "causal_start": {
                "index": first_open_break_index,
                "timestamp": str(bars[first_open_break_index].get("timestamp") or ""),
                "session_open": session_open,
            },
            "hindsight_resolution": {
                "resolution_status": "OPEN_RECLAIMED" if open_reclaimed else "OPEN_RIGHT_CENSORED",
                "resolution_timestamp": next((m["timestamp"] for m in markers if m["kind"] == "OPEN_RECLAIM"), None),
                "right_censored": not open_reclaimed,
            },
            "future_resolution_not_used_to_define_start": True,
        })
    if open_buy_nonresponse is not None:
        journeys.append({
            **base_identity,
            "schema": SCHEMA,
            "journey_kind": "BUY_NONRESPONSE_WINDOW",
            "causal_start": open_buy_nonresponse,
            "hindsight_resolution": {"resolution_status": "OPEN_RIGHT_CENSORED", "resolution_timestamp": None, "right_censored": True},
            "future_resolution_not_used_to_define_start": True,
        })
    if open_sell_resilience is not None:
        journeys.append({
            **base_identity,
            "schema": SCHEMA,
            "journey_kind": "SELL_RESILIENCE_WINDOW",
            "causal_start": open_sell_resilience,
            "hindsight_resolution": {"resolution_status": "OPEN_RIGHT_CENSORED", "resolution_timestamp": None, "right_censored": True},
            "future_resolution_not_used_to_define_start": True,
        })

    right_censored = sum(1 for j in journeys if bool(j.get("hindsight_resolution", {}).get("right_censored")))
    day = {
        **base_identity,
        "schema": SCHEMA,
        "status": STATUS,
        "zero_session_eligible": False,
        "bar_count": len(bars),
        "first_timestamp": str(bars[0].get("timestamp") or ""),
        "last_timestamp": last_ts,
        "session_open": session_open,
        "final_close": _safe_float(bars[-1].get("close")),
        "running_high": run_hi,
        "running_low": run_lo,
        "no_forced_event": len(journeys) == 0,
        "formation_run_count": len(runs),
        "semantic_marker_count": len(markers),
        "event_journey_count": len(journeys),
        "open_right_censored_journey_count": right_censored,
        "timestamp_discontinuity_marker_count": gap_markers,
        "carry_in": carry_in,
        "previous_governed_date": previous_governed_date,
        "availability": availability,
        "causal_view_separate_from_hindsight": True,
        "terminal_carry_state": {
            "date": trading_date,
            "last_timestamp": last_ts,
            "final_close": _safe_float(bars[-1].get("close")),
            "running_high": run_hi,
            "running_low": run_lo,
            "open_broken": open_broken,
            "open_reclaimed": open_reclaimed,
            "last_state_key": runs[-1]["state_key"] if runs else None,
            "unresolved_journey_kinds": sorted(j["journey_kind"] for j in journeys if bool(j.get("hindsight_resolution", {}).get("right_censored"))),
        },
    }
    return day, runs, journeys


def _build_day_index(db: sqlite3.Connection, sources: Sequence[Mapping[str, Any]]) -> tuple[list[str], int, int]:
    db.execute("DROP TABLE IF EXISTS days")
    db.execute("DROP TABLE IF EXISTS calendar")
    db.execute("CREATE TABLE days(source_order INTEGER, source TEXT, ticker TEXT, day TEXT, bar_count INTEGER, first_timestamp TEXT, last_timestamp TEXT, final_close REAL, PRIMARY KEY(source,ticker,day))")
    all_dates: set[str] = set()
    total_days = total_rows = 0
    for source_order, src in enumerate(sources):
        source = str(src["source_name"])
        for packet in v12r._iter_cached(source):
            ticker = str(packet.get("ticker") or "")
            day = str(packet.get("date") or "")
            bars = [dict(x) for x in packet.get("bars", [])]
            if not ticker or not day:
                raise RuntimeError(f"V30_BAD_PACKET_IDENTITY:{source}:{ticker}:{day}")
            first_ts = str(bars[0].get("timestamp") or "") if bars else None
            last_ts = str(bars[-1].get("timestamp") or "") if bars else None
            final_close = _safe_float(bars[-1].get("close")) if bars else None
            db.execute("INSERT INTO days VALUES(?,?,?,?,?,?,?,?)", (source_order, source, ticker, day, len(bars), first_ts, last_ts, final_close))
            all_dates.add(day)
            total_days += 1
            total_rows += len(bars)
    dates = sorted(all_dates)
    db.execute("CREATE TABLE calendar(day TEXT PRIMARY KEY, previous_day TEXT)")
    for i, day in enumerate(dates):
        prev = dates[i - 1] if i > 0 else None
        db.execute("INSERT INTO calendar VALUES(?,?)", (day, prev))
    db.commit()
    return dates, total_days, total_rows


def _carry_for(db: sqlite3.Connection, *, ticker: str, day: str, source: str) -> tuple[dict[str, Any] | None, str | None]:
    row = db.execute("SELECT previous_day FROM calendar WHERE day=?", (day,)).fetchone()
    prev_day = str(row[0]) if row and row[0] else None
    if prev_day is None:
        return None, None
    if source == "Raw April 01-30-2025.csv" and prev_day <= "2025-02-28":
        return {
            "status": "BLOCKED_BY_RESERVED_OOS_GAP",
            "reason": "March 2025 reserved OOS remains untouched; cross-date carry is not bridged across the withheld month",
        }, None
    prior = db.execute(
        "SELECT source,bar_count,first_timestamp,last_timestamp,final_close FROM days WHERE ticker=? AND day=? ORDER BY source_order DESC LIMIT 1",
        (ticker, prev_day),
    ).fetchone()
    if prior is None:
        return {"status": "NO_TICKER_PACKET_ON_PREVIOUS_GOVERNED_DATE", "previous_governed_date": prev_day}, prev_day
    return {
        "status": "EXACT_PREVIOUS_GOVERNED_DATE_PACKET",
        "previous_governed_date": prev_day,
        "source": prior[0],
        "bar_count": int(prior[1]),
        "first_timestamp": prior[2],
        "last_timestamp": prior[3],
        "final_close": prior[4],
    }, prev_day


def _source_checkpoint_ok(path: Path, src: Mapping[str, Any], artifact_digest: str) -> bool:
    if not path.is_file():
        return False
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        obj.get("schema") == SCHEMA
        and obj.get("status") == "PASS"
        and obj.get("artifact_digest") == artifact_digest
        and obj.get("source") == src.get("source_name")
        and obj.get("source_sha256") == src.get("source_sha256")
        and int(obj.get("ticker_days", -1)) == int(src.get("ticker_days", -2))
        and int(obj.get("minute_rows", -1)) == int(src.get("rows", -2))
    )


def run(*, output_root: Path, artifact_digest: str) -> dict[str, Any]:
    digest = artifact_digest.removeprefix("sha256:")
    if digest != ROOT_V22_DIGEST:
        raise RuntimeError(f"V30_ARTIFACT_DIGEST_MISMATCH:{digest}")
    sources = governed_sources_from_durable_cache()
    output_root.mkdir(parents=True, exist_ok=True)
    index_path = output_root / "day-index.sqlite3"
    db = sqlite3.connect(index_path)
    dates, indexed_days, indexed_rows = _build_day_index(db, sources)
    if indexed_days != EXPECTED_TICKER_DAYS or indexed_rows != EXPECTED_MINUTE_ROWS:
        raise RuntimeError(f"V30_INDEX_RECONCILIATION_FAIL:{indexed_days}:{indexed_rows}")

    totals = Counter()
    source_summaries: list[dict[str, Any]] = []
    sample: list[dict[str, Any]] = []
    reused_sources = 0

    for src in sources:
        source = str(src["source_name"])
        source_dir = output_root / _slug(source)
        source_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = source_dir / "checkpoint.json"
        if _source_checkpoint_ok(checkpoint, src, f"sha256:{digest}"):
            cp = json.loads(checkpoint.read_text(encoding="utf-8"))
            source_summaries.append(cp)
            for key in ("ticker_days", "minute_rows", "zero_session_ticker_days", "formation_runs", "semantic_markers", "event_journeys", "right_censored_journeys", "no_forced_event_ticker_days"):
                totals[key] += int(cp.get(key, 0))
            reused_sources += 1
            continue

        ticker_day_path = source_dir / "ticker-days.jsonl.gz"
        runs_path = source_dir / "formation-runs.jsonl.gz"
        journeys_path = source_dir / "event-journeys.jsonl.gz"
        td_tmp = ticker_day_path.with_suffix(ticker_day_path.suffix + ".tmp")
        r_tmp = runs_path.with_suffix(runs_path.suffix + ".tmp")
        j_tmp = journeys_path.with_suffix(journeys_path.suffix + ".tmp")
        counts = Counter()
        allow_hh = source == str(DEC_2024_CONTRACT["source_name"])
        with gzip.open(td_tmp, "wt", encoding="utf-8", newline="\n") as td_fh, gzip.open(r_tmp, "wt", encoding="utf-8", newline="\n") as r_fh, gzip.open(j_tmp, "wt", encoding="utf-8", newline="\n") as j_fh:
            for packet in v12r._iter_cached(source):
                ticker = str(packet.get("ticker") or "")
                day = str(packet.get("date") or "")
                bars = [dict(x) for x in packet.get("bars", [])]
                carry, prev_day = _carry_for(db, ticker=ticker, day=day, source=source)
                td, runs, journeys = enrich_ticker_day(
                    bars,
                    source=source,
                    source_identity=src,
                    ticker=ticker,
                    trading_date=day,
                    carry_in=carry,
                    previous_governed_date=prev_day,
                    allow_haka_haki=allow_hh,
                )
                td_fh.write(json.dumps(td, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                for rec in runs:
                    r_fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                for rec in journeys:
                    j_fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                counts["ticker_days"] += 1
                counts["minute_rows"] += len(bars)
                counts["zero_session_ticker_days"] += int(not bars)
                counts["formation_runs"] += len(runs)
                counts["semantic_markers"] += int(td["semantic_marker_count"])
                counts["event_journeys"] += len(journeys)
                counts["right_censored_journeys"] += int(td["open_right_censored_journey_count"])
                counts["no_forced_event_ticker_days"] += int(td["no_forced_event"])
                if len(sample) < 100:
                    sample.append(td)
        td_tmp.replace(ticker_day_path); r_tmp.replace(runs_path); j_tmp.replace(journeys_path)
        if counts["ticker_days"] != int(src["ticker_days"]) or counts["minute_rows"] != int(src["rows"]):
            raise RuntimeError(f"V30_SOURCE_RECONCILIATION_FAIL:{source}:{dict(counts)}")
        cp = {
            "schema": SCHEMA,
            "status": "PASS",
            "artifact_digest": f"sha256:{digest}",
            "source": source,
            "source_drive_id": src.get("source_drive_id"),
            "source_sha256": src.get("source_sha256"),
            "generation_id": src.get("generation_id"),
            "semantic_manifest_fingerprint": src.get("semantic_manifest_fingerprint"),
            **{k: int(v) for k, v in counts.items()},
            "ticker_day_file": ticker_day_path.name,
            "formation_run_file": runs_path.name,
            "event_journey_file": journeys_path.name,
            "causal_state_not_rewritten_by_hindsight": True,
            "raw_reread": False,
            "reserved_oos_untouched": True,
        }
        checkpoint.write_text(json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8")
        source_summaries.append(cp)
        totals.update(counts)

    if totals["ticker_days"] != EXPECTED_TICKER_DAYS or totals["minute_rows"] != EXPECTED_MINUTE_ROWS or totals["zero_session_ticker_days"] != EXPECTED_ZERO_SESSION:
        raise RuntimeError(f"V30_GLOBAL_RECONCILIATION_FAIL:{dict(totals)}")

    sample_path = output_root / "compact-sample.jsonl.gz"
    _write_gz_jsonl(sample_path, sample)
    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "artifact_digest": f"sha256:{digest}",
        "contract": {
            "append_only_sidecar": True,
            "v21_v22_v23_v24_v25_not_rewritten": True,
            "reads_durable_tf1m_cache_not_raw": True,
            "manual_reference_not_used_as_hidden_label": True,
            "causal_view_separate_from_hindsight": True,
            "no_forced_event": True,
            "unknown_unproven_preserved": True,
            "reserved_oos_untouched": True,
            "cross_date_carry_blocked_across_reserved_oos_gap": True,
            "downstream_v3_research_required_only_after_enrichment_reconciliation": True,
        },
        "reconciliation": {
            "pass": True,
            "ticker_days": int(totals["ticker_days"]),
            "minute_rows": int(totals["minute_rows"]),
            "zero_session_ticker_days": int(totals["zero_session_ticker_days"]),
            "formation_runs": int(totals["formation_runs"]),
            "semantic_markers": int(totals["semantic_markers"]),
            "event_journeys": int(totals["event_journeys"]),
            "right_censored_journeys": int(totals["right_censored_journeys"]),
            "no_forced_event_ticker_days": int(totals["no_forced_event_ticker_days"]),
            "sources": len(sources),
            "governed_dates": len(dates),
            "reused_pass_sources": reused_sources,
        },
        "source_summaries": source_summaries,
        "semantic_capabilities": [
            "FORMATION_SEQUENCE_RUNS",
            "SEMANTIC_MARKERS_WITH_EXACT_TIME",
            "EVENT_JOURNEYS",
            "NO_FORCED_EVENT",
            "OPEN_RIGHT_CENSORED",
            "CROSS_DATE_CARRY",
            "SOURCE_GAP_TIMING_UNCERTAINTY",
            "FAILED_RECOVERY_EVALUATION",
            "PULLBACK_RECLAIM_EVALUATION",
            "BUY_NONRESPONSE_WINDOWS",
            "SELL_RESILIENCE_WINDOWS",
            "OPEN_BREAK_RECLAIM",
            "EXPLICIT_UNKNOWN_UNPROVEN_AVAILABILITY",
        ],
        "manifest_sha256": None,
    }
    manifest["manifest_sha256"] = _digest_obj({k: v for k, v in manifest.items() if k != "manifest_sha256"})
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    db.close()
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output-root", required=True)
    p.add_argument("--artifact-digest", required=True)
    a = p.parse_args()
    manifest = run(output_root=Path(a.output_root), artifact_digest=str(a.artifact_digest))
    print(json.dumps({"schema": manifest["schema"], "status": manifest["status"], "reconciliation": manifest["reconciliation"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
