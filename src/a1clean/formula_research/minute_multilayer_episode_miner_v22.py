from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .durable_cache_catalog import governed_sources_from_durable_cache
from .haka_haki_reconstruction import DEC_2024_CONTRACT, _assert_contract, reconstruct_bar
from .minute_behavior_census_v21 import _canon_digest_row, _f, _flow_price_relation, _pct, _sign

SCHEMA = "A1_MINUTE_MULTILAYER_EPISODE_MINER_V22"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")


def _flow_direction(nbss: float | None, flow_ok: bool) -> str:
    if not flow_ok or nbss is None:
        return "UNKNOWN"
    if nbss > 0:
        return "BUY"
    if nbss < 0:
        return "SELL"
    return "NEUTRAL"


def _compare_level(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "UNKNOWN"
    if cur > prev:
        return "ACCEL"
    if cur < prev:
        return "DECEL"
    return "FLAT"


def _compare_abs(cur: float | None, prev: float | None) -> str:
    if cur is None or prev is None:
        return "UNKNOWN"
    return _compare_level(abs(cur), abs(prev))


def _haka_dominance(haka: float | None, haki: float | None) -> str:
    if haka is None or haki is None:
        return "UNKNOWN"
    if haka > haki:
        return "HAKA"
    if haki > haka:
        return "HAKI"
    return "BALANCED"


def _token(
    *,
    relation: str,
    price_dir: str,
    volume_dir: str,
    value_dir: str,
    flow_dir: str,
    flow_accel: str,
    value_accel: str,
    fresh_high: bool,
    fresh_low: bool,
    haka_dom: str,
) -> str:
    return "|".join(
        (
            relation,
            f"P_{price_dir}",
            f"VOL_{volume_dir}",
            f"VALUE_{value_dir}",
            f"FLOW_{flow_dir}",
            f"FLOWEFF_{flow_accel}",
            f"VALACT_{value_accel}",
            f"HI_{'FRESH' if fresh_high else 'NO'}",
            f"LO_{'FRESH' if fresh_low else 'NO'}",
            f"HH_{haka_dom}",
        )
    )


def _set_first(milestones: dict[str, str | None], key: str, timestamp: str, condition: bool) -> None:
    if condition and milestones.get(key) is None:
        milestones[key] = timestamp


def _empty_summary(*, allow_haka_haki: bool) -> dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(_canon_digest_row({"rows": 0, "evidence": "NO_SESSION_ELIGIBLE_BAR"}))
    return {
        "rows": 0,
        "zero_session_eligible": True,
        "first_timestamp": None,
        "last_timestamp": None,
        "first_open": None,
        "final_close": None,
        "running_high": None,
        "running_low": None,
        "haka_haki_proven_source_scope": allow_haka_haki,
        "episode_run_count": 0,
        "state_transition_count": 0,
        "milestones": {},
        "milestone_counts": {},
        "response_latency_events": [],
        "relation_state_counts": {},
        "token_counts": {},
        "episode_evidence_digest_sha256": digest.hexdigest(),
    }


def mine_ticker_day(
    bars: Sequence[Mapping[str, Any]],
    *,
    allow_haka_haki: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not bars:
        return _empty_summary(allow_haka_haki=allow_haka_haki), []

    first_open = _f(bars[0].get("open"))
    prev_close: float | None = None
    prev_volume: float | None = None
    prev_value: float | None = None
    prev_nbss: float | None = None
    prev_price_dir: str | None = None
    prev_flow_dir: str | None = None
    prev_haka_dom: str | None = None
    run_hi: float | None = None
    run_lo: float | None = None

    relation_counts: Counter[str] = Counter()
    token_counts: Counter[str] = Counter()
    milestone_counts: Counter[str] = Counter()
    milestones: dict[str, str | None] = {
        "FIRST_BUY_FLOW_TIME": None,
        "FIRST_SELL_FLOW_TIME": None,
        "FIRST_PROVEN_NEUTRAL_FLOW_TIME": None,
        "FIRST_PRICE_UP_TIME": None,
        "FIRST_PRICE_DOWN_TIME": None,
        "FIRST_FRESH_HIGH_TIME": None,
        "FIRST_FRESH_LOW_TIME": None,
        "FIRST_VALUE_ACCEL_TIME": None,
        "FIRST_VALUE_DECEL_TIME": None,
        "FIRST_FLOW_EFFORT_ACCEL_TIME": None,
        "FIRST_FLOW_EFFORT_DECEL_TIME": None,
        "FIRST_BUY_NON_RESPONSE_TIME": None,
        "FIRST_BUY_PRICE_RESPONSE_TIME": None,
        "FIRST_SELL_RESILIENCE_TIME": None,
        "FIRST_SELL_PRICE_RESPONSE_TIME": None,
        "FIRST_PRICE_REVERSAL_TIME": None,
        "FIRST_FLOW_DOMINANCE_CHANGE_TIME": None,
        "FIRST_HAKA_HAKI_DOMINANCE_CHANGE_TIME": None,
    }
    response_latency_events: list[dict[str, Any]] = []
    open_buy_nonresponse: dict[str, Any] | None = None
    open_sell_resilience: dict[str, Any] | None = None

    runs: list[dict[str, Any]] = []
    active_run: dict[str, Any] | None = None
    digest = hashlib.sha256()

    for i, raw in enumerate(bars):
        timestamp = str(raw.get("timestamp") or "")
        op = _f(raw.get("open"))
        hi = _f(raw.get("high"))
        lo = _f(raw.get("low"))
        close = _f(raw.get("close"))
        volume = _f(raw.get("volume"))
        trade_value = _f(raw.get("trade_value"))
        flow_ok = bool(raw.get("flow_available", False)) and bool(raw.get("mechanism_eligible", False))
        nbss = _f(raw.get("nbss")) if flow_ok else None

        old_hi = run_hi
        old_lo = run_lo
        if hi is not None:
            run_hi = hi if run_hi is None else max(run_hi, hi)
        if lo is not None:
            run_lo = lo if run_lo is None else min(run_lo, lo)
        fresh_high = hi is not None and (old_hi is None or hi > old_hi)
        fresh_low = lo is not None and (old_lo is None or lo < old_lo)

        price_delta_pct = _pct(close, prev_close) if prev_close not in (None, 0) else None
        path_pct = _pct(close, first_open) if first_open not in (None, 0) else None
        price_dir = _sign(price_delta_pct)
        volume_delta = None if volume is None or prev_volume is None else volume - prev_volume
        value_delta = None if trade_value is None or prev_value is None else trade_value - prev_value
        nbss_delta = None if nbss is None or prev_nbss is None else nbss - prev_nbss
        volume_dir = _sign(volume_delta)
        value_dir = _sign(value_delta)
        flow_dir = _flow_direction(nbss, flow_ok)
        flow_accel = _compare_abs(nbss, prev_nbss) if flow_ok else "UNKNOWN"
        value_accel = _compare_level(trade_value, prev_value)
        relation = _flow_price_relation(nbss, price_delta_pct, flow_ok)

        haka = None
        haki = None
        haka_dom = "UNKNOWN"
        reconstruction_status = "NOT_IN_PROVEN_HAKA_HAKI_SOURCE_SCOPE"
        if allow_haka_haki:
            rec = reconstruct_bar(raw)
            reconstruction_status = str(rec["status"])
            haka = _f(rec.get("haka"))
            haki = _f(rec.get("haki"))
            haka_dom = _haka_dominance(haka, haki)

        tok = _token(
            relation=relation,
            price_dir=price_dir,
            volume_dir=volume_dir,
            value_dir=value_dir,
            flow_dir=flow_dir,
            flow_accel=flow_accel,
            value_accel=value_accel,
            fresh_high=fresh_high,
            fresh_low=fresh_low,
            haka_dom=haka_dom,
        )
        relation_counts[relation] += 1
        token_counts[tok] += 1

        _set_first(milestones, "FIRST_BUY_FLOW_TIME", timestamp, flow_dir == "BUY")
        _set_first(milestones, "FIRST_SELL_FLOW_TIME", timestamp, flow_dir == "SELL")
        _set_first(milestones, "FIRST_PROVEN_NEUTRAL_FLOW_TIME", timestamp, flow_dir == "NEUTRAL")
        _set_first(milestones, "FIRST_PRICE_UP_TIME", timestamp, price_dir == "UP")
        _set_first(milestones, "FIRST_PRICE_DOWN_TIME", timestamp, price_dir == "DOWN")
        _set_first(milestones, "FIRST_FRESH_HIGH_TIME", timestamp, fresh_high)
        _set_first(milestones, "FIRST_FRESH_LOW_TIME", timestamp, fresh_low)
        _set_first(milestones, "FIRST_VALUE_ACCEL_TIME", timestamp, value_accel == "ACCEL")
        _set_first(milestones, "FIRST_VALUE_DECEL_TIME", timestamp, value_accel == "DECEL")
        _set_first(milestones, "FIRST_FLOW_EFFORT_ACCEL_TIME", timestamp, flow_accel == "ACCEL")
        _set_first(milestones, "FIRST_FLOW_EFFORT_DECEL_TIME", timestamp, flow_accel == "DECEL")
        _set_first(milestones, "FIRST_BUY_NON_RESPONSE_TIME", timestamp, relation == "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE")
        _set_first(milestones, "FIRST_BUY_PRICE_RESPONSE_TIME", timestamp, relation == "BUY_FLOW_PRICE_ADVANCE")
        _set_first(milestones, "FIRST_SELL_RESILIENCE_TIME", timestamp, relation == "SELL_FLOW_PRICE_RESILIENCE")
        _set_first(milestones, "FIRST_SELL_PRICE_RESPONSE_TIME", timestamp, relation == "SELL_FLOW_PRICE_DECLINE")

        if prev_price_dir in {"UP", "DOWN"} and price_dir in {"UP", "DOWN"} and price_dir != prev_price_dir:
            _set_first(milestones, "FIRST_PRICE_REVERSAL_TIME", timestamp, True)
            milestone_counts["PRICE_REVERSAL"] += 1
        if prev_flow_dir in {"BUY", "SELL"} and flow_dir in {"BUY", "SELL"} and flow_dir != prev_flow_dir:
            _set_first(milestones, "FIRST_FLOW_DOMINANCE_CHANGE_TIME", timestamp, True)
            milestone_counts["FLOW_DOMINANCE_CHANGE"] += 1
        if prev_haka_dom in {"HAKA", "HAKI"} and haka_dom in {"HAKA", "HAKI"} and haka_dom != prev_haka_dom:
            _set_first(milestones, "FIRST_HAKA_HAKI_DOMINANCE_CHANGE_TIME", timestamp, True)
            milestone_counts["HAKA_HAKI_DOMINANCE_CHANGE"] += 1

        if relation == "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE":
            if open_buy_nonresponse is None:
                open_buy_nonresponse = {"start_index": i, "start_timestamp": timestamp}
        elif relation == "BUY_FLOW_PRICE_ADVANCE" and open_buy_nonresponse is not None:
            response_latency_events.append({
                "kind": "BUY_NONRESPONSE_TO_ADVANCE",
                "start_timestamp": open_buy_nonresponse["start_timestamp"],
                "response_timestamp": timestamp,
                "latency_rows": i - int(open_buy_nonresponse["start_index"]),
            })
            open_buy_nonresponse = None
        elif flow_dir != "BUY":
            open_buy_nonresponse = None

        if relation == "SELL_FLOW_PRICE_RESILIENCE":
            if open_sell_resilience is None:
                open_sell_resilience = {"start_index": i, "start_timestamp": timestamp}
        elif relation == "SELL_FLOW_PRICE_DECLINE" and open_sell_resilience is not None:
            response_latency_events.append({
                "kind": "SELL_RESILIENCE_TO_DECLINE",
                "start_timestamp": open_sell_resilience["start_timestamp"],
                "response_timestamp": timestamp,
                "latency_rows": i - int(open_sell_resilience["start_index"]),
            })
            open_sell_resilience = None
        elif flow_dir != "SELL":
            open_sell_resilience = None

        if active_run is None or active_run["token"] != tok:
            if active_run is not None:
                runs.append(active_run)
            active_run = {
                "token": tok,
                "start_timestamp": timestamp,
                "end_timestamp": timestamp,
                "start_index": i,
                "end_index": i,
                "row_count": 1,
                "start_close": close,
                "end_close": close,
                "start_nbss": nbss,
                "end_nbss": nbss,
                "start_trade_value": trade_value,
                "end_trade_value": trade_value,
                "relation": relation,
                "flow_direction": flow_dir,
                "price_direction": price_dir,
                "flow_effort_change": flow_accel,
                "value_activity_change": value_accel,
                "haka_haki_dominance": haka_dom,
            }
        else:
            active_run["end_timestamp"] = timestamp
            active_run["end_index"] = i
            active_run["row_count"] += 1
            active_run["end_close"] = close
            active_run["end_nbss"] = nbss
            active_run["end_trade_value"] = trade_value

        digest.update(_canon_digest_row({
            "i": i,
            "timestamp": timestamp,
            "open": op,
            "high": hi,
            "low": lo,
            "close": close,
            "volume": volume,
            "trade_value": trade_value,
            "flow_available": bool(raw.get("flow_available", False)),
            "mechanism_eligible": bool(raw.get("mechanism_eligible", False)),
            "nbss": nbss,
            "nbss_delta": nbss_delta,
            "price_delta_pct": price_delta_pct,
            "path_pct": path_pct,
            "flow_direction": flow_dir,
            "flow_effort_change": flow_accel,
            "value_activity_change": value_accel,
            "relation": relation,
            "fresh_high": fresh_high,
            "fresh_low": fresh_low,
            "haka": haka,
            "haki": haki,
            "haka_haki_dominance": haka_dom,
            "haka_haki_reconstruction_status": reconstruction_status,
            "token": tok,
        }))

        if close is not None:
            prev_close = close
        if volume is not None:
            prev_volume = volume
        if trade_value is not None:
            prev_value = trade_value
        if flow_ok and nbss is not None:
            prev_nbss = nbss
        prev_price_dir = price_dir
        prev_flow_dir = flow_dir
        if haka_dom != "UNKNOWN":
            prev_haka_dom = haka_dom

    if active_run is not None:
        runs.append(active_run)

    for key, value in milestones.items():
        if value is not None:
            milestone_counts[key] += 1

    return {
        "rows": len(bars),
        "zero_session_eligible": False,
        "first_timestamp": str(bars[0].get("timestamp") or ""),
        "last_timestamp": str(bars[-1].get("timestamp") or ""),
        "first_open": first_open,
        "final_close": _f(bars[-1].get("close")),
        "running_high": run_hi,
        "running_low": run_lo,
        "haka_haki_proven_source_scope": allow_haka_haki,
        "episode_run_count": len(runs),
        "state_transition_count": max(0, len(runs) - 1),
        "milestones": milestones,
        "milestone_counts": dict(milestone_counts),
        "response_latency_events": response_latency_events,
        "relation_state_counts": dict(relation_counts),
        "token_counts": dict(token_counts),
        "episode_evidence_digest_sha256": digest.hexdigest(),
    }, runs


def _write_jsonl_gz_line(fh: Any, obj: Mapping[str, Any]) -> None:
    fh.write(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")


def build_report(*, ticker_day_output: str | None = None, episode_output: str | None = None) -> dict[str, Any]:
    if v11.RESERVED_OOS in (v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B):
        raise AssertionError("RESERVED_OOS_MUST_REMAIN_OUTSIDE_DEVELOPMENT")

    sources = governed_sources_from_durable_cache()
    counters = {b: {"ticker_days": 0, "minute_rows": 0, "episode_runs": 0, "zero_session_ticker_days": 0} for b in BLOCKS}
    relation_counts = {b: Counter() for b in BLOCKS}
    transition_counts = {b: Counter() for b in BLOCKS}
    milestone_counts = {b: Counter() for b in BLOCKS}
    response_latency_hist = {b: defaultdict(Counter) for b in BLOCKS}
    source_accounting: list[dict[str, Any]] = []
    global_digest = hashlib.sha256()

    td_fh = gzip.open(ticker_day_output, "wt", encoding="utf-8", newline="\n") if ticker_day_output else None
    ep_fh = gzip.open(episode_output, "wt", encoding="utf-8", newline="\n") if episode_output else None
    try:
        for src in sources:
            source = str(src["source_name"])
            block = v11._block_for(source)
            allow_haka = source == str(DEC_2024_CONTRACT["source_name"])
            if allow_haka:
                _assert_contract(src)

            src_ticker_days = 0
            src_rows = 0
            src_zero = 0
            src_runs = 0
            src_digest = hashlib.sha256()

            for packet in v12r._iter_cached(source):
                ticker = str(packet.get("ticker") or "")
                date = str(packet.get("date") or "")
                bars = [dict(x) for x in packet.get("bars", [])]
                summary, runs = mine_ticker_day(bars, allow_haka_haki=allow_haka)

                src_ticker_days += 1
                src_rows += int(summary["rows"])
                src_runs += len(runs)
                counters[block]["ticker_days"] += 1
                counters[block]["minute_rows"] += int(summary["rows"])
                counters[block]["episode_runs"] += len(runs)
                if bool(summary.get("zero_session_eligible")):
                    src_zero += 1
                    counters[block]["zero_session_ticker_days"] += 1

                for state, n in dict(summary.get("relation_state_counts", {})).items():
                    relation_counts[block][state] += int(n)
                for key, n in dict(summary.get("milestone_counts", {})).items():
                    milestone_counts[block][key] += int(n)
                for left, right in zip(runs, runs[1:]):
                    transition_counts[block][f"{left['token']} -> {right['token']}"] += 1
                for event in list(summary.get("response_latency_events", [])):
                    response_latency_hist[block][str(event["kind"])][int(event["latency_rows"])] += 1

                record = {"source": source, "block": block, "ticker": ticker, "date": date, **summary}
                if td_fh is not None:
                    _write_jsonl_gz_line(td_fh, record)
                for run in runs:
                    if ep_fh is not None:
                        _write_jsonl_gz_line(ep_fh, {"source": source, "block": block, "ticker": ticker, "date": date, **run})

                packet_digest = _canon_digest_row({
                    "source": source,
                    "ticker": ticker,
                    "date": date,
                    "rows": summary["rows"],
                    "episode_run_count": summary["episode_run_count"],
                    "episode_evidence_digest_sha256": summary["episode_evidence_digest_sha256"],
                })
                src_digest.update(packet_digest)
                global_digest.update(packet_digest)

            source_accounting.append({
                "source_name": source,
                "block": block,
                "source_drive_id": src.get("source_drive_id"),
                "source_sha256": src.get("source_sha256"),
                "generation_id": src.get("generation_id"),
                "catalog_ticker_days": int(src.get("ticker_days", 0)),
                "processed_ticker_days": src_ticker_days,
                "processed_minute_rows": src_rows,
                "episode_runs": src_runs,
                "zero_session_ticker_days": src_zero,
                "haka_haki_reconstruction_enabled": allow_haka,
                "ticker_day_accounting_pass": src_ticker_days == int(src.get("ticker_days", 0)),
                "source_episode_digest_sha256": src_digest.hexdigest(),
            })
    finally:
        if td_fh is not None:
            td_fh.close()
        if ep_fh is not None:
            ep_fh.close()

    if any(not x["ticker_day_accounting_pass"] for x in source_accounting):
        raise AssertionError("TICKER_DAY_ACCOUNTING_MISMATCH")

    totals = {
        "ticker_days": sum(int(counters[b]["ticker_days"]) for b in BLOCKS),
        "minute_rows": sum(int(counters[b]["minute_rows"]) for b in BLOCKS),
        "episode_runs": sum(int(counters[b]["episode_runs"]) for b in BLOCKS),
        "zero_session_ticker_days": sum(int(counters[b]["zero_session_ticker_days"]) for b in BLOCKS),
    }
    latency = {
        b: {kind: {str(k): int(v) for k, v in sorted(hist.items())} for kind, hist in response_latency_hist[b].items()}
        for b in BLOCKS
    }
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "method": "EVERY_TF1M_BAR_TO_CAUSAL_MULTI_LAYER_CHANGE_EPISODES_NO_5M_INPUT_FILTER",
        "scope": {
            "timeframe": "1M",
            "every_ticker_day_processed": True,
            "every_cached_session_bar_processed": True,
            "publication_slot_filter_used": False,
            "telegram_five_minute_is_output_only": True,
            "reserved_oos_untouched": v11.RESERVED_OOS,
        },
        "episode_contract": {
            "continuous_evidence_before_labels": True,
            "exact_source_timestamp_preserved": True,
            "price_and_formation_read_together": True,
            "flow_price_nonresponse_and_response_latency_preserved": True,
            "activity_acceleration_deceleration_preserved": True,
            "price_reversal_time_preserved": True,
            "flow_dominance_change_time_preserved": True,
            "haka_haki_dominance_change_dec2024_only_when_proven": True,
            "future_outcome_used_in_state": False,
            "arbitrary_thresholds_added": False,
            "missing_never_zero": True,
        },
        "currently_unavailable_unproven_lanes": [
            "separate_NFSS_when_not_bound",
            "broker_participant_gross_buy_sell_net",
            "tick_time_and_trade",
            "L1_L2_orderbook_queue",
            "financial_issuer_sector_context_without_causal_timestamp",
        ],
        "counters": counters,
        "totals": totals,
        "source_accounting": source_accounting,
        "relation_state_counts": {b: dict(relation_counts[b]) for b in BLOCKS},
        "milestone_counts": {b: dict(milestone_counts[b]) for b in BLOCKS},
        "response_latency_hist_rows": latency,
        "top_joint_state_transitions": {
            b: [{"transition": k, "count": int(v)} for k, v in transition_counts[b].most_common(500)]
            for b in BLOCKS
        },
        "global_episode_evidence_digest_sha256": global_digest.hexdigest(),
        "artifacts": {
            "ticker_day_episode_summary_jsonl_gz": ticker_day_output,
            "episode_runs_jsonl_gz": episode_output,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--ticker-day-output", required=True)
    p.add_argument("--episode-output", required=True)
    a = p.parse_args()
    report = build_report(ticker_day_output=a.ticker_day_output, episode_output=a.episode_output)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"schema": report["schema"], "totals": report["totals"], "digest": report["global_episode_evidence_digest_sha256"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
