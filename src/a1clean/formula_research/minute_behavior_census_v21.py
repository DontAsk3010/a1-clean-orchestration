from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .durable_cache_catalog import governed_sources_from_durable_cache
from .haka_haki_reconstruction import DEC_2024_CONTRACT, _assert_contract, reconstruct_bar

SCHEMA = "A1_MINUTE_BEHAVIOR_CENSUS_V21"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"
BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return float(a) / float(b)


def _pct(a: float | None, b: float | None) -> float | None:
    ratio = _safe_div(a, b)
    return None if ratio is None else (ratio - 1.0) * 100.0


def _sign(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value > 0:
        return "UP"
    if value < 0:
        return "DOWN"
    return "FLAT"


def _canon_digest_row(obj: Mapping[str, Any]) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _flow_price_relation(nbss: float | None, price_delta_pct: float | None, flow_ok: bool) -> str:
    if not flow_ok or nbss is None:
        return "NO_PROVEN_FLOW"
    if nbss > 0:
        if price_delta_pct is None:
            return "BUY_FLOW_PRICE_RESPONSE_UNKNOWN"
        if price_delta_pct > 0:
            return "BUY_FLOW_PRICE_ADVANCE"
        return "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE"
    if nbss < 0:
        if price_delta_pct is None:
            return "SELL_FLOW_PRICE_RESPONSE_UNKNOWN"
        if price_delta_pct < 0:
            return "SELL_FLOW_PRICE_DECLINE"
        return "SELL_FLOW_PRICE_RESILIENCE"
    return "PROVEN_NEUTRAL_FLOW"


def _activity_relation(volume_change: float | None, value_change: float | None, price_delta_pct: float | None) -> str:
    return "|".join(
        (
            f"VOL_{_sign(volume_change)}",
            f"VALUE_{_sign(value_change)}",
            f"PRICE_{_sign(price_delta_pct)}",
        )
    )


def _empty_summary(*, allow_haka_haki: bool) -> dict[str, Any]:
    return {
        "rows": 0,
        "session_evidence_status": "NO_SESSION_ELIGIBLE_BARS",
        "first_timestamp": None,
        "last_timestamp": None,
        "first_open": None,
        "first_close": None,
        "final_close": None,
        "running_high": None,
        "running_low": None,
        "day_return_pct": None,
        "total_volume": 0.0,
        "total_trade_value": 0.0,
        "flow_rows": 0,
        "flow_coverage_fraction": None,
        "positive_flow_rows": 0,
        "negative_flow_rows": 0,
        "nbss_sum": None,
        "abs_nbss_sum": None,
        "haka_haki_proven_source_scope": allow_haka_haki,
        "haka_haki_rows": 0,
        "haka_haki_coverage_fraction": None,
        "haka_sum": None,
        "haki_sum": None,
        "relation_state_counts": {},
        "activity_relation_counts": {},
        "price_direction_counts": {},
        "flow_direction_counts": {},
        "haka_haki_reconstruction_status_counts": {},
        "relation_transition_count": 0,
        "first_relation_state": None,
        "last_relation_state": None,
        "minute_evidence_digest_sha256": hashlib.sha256().hexdigest(),
    }


def scan_ticker_day(
    bars: Sequence[Mapping[str, Any]],
    *,
    allow_haka_haki: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not bars:
        return (_empty_summary(allow_haka_haki=allow_haka_haki), [])

    first_open = _f(bars[0].get("open"))
    first_close = _f(bars[0].get("close"))
    run_hi: float | None = None
    run_lo: float | None = None
    prev_close: float | None = None
    prev_volume: float | None = None
    prev_value: float | None = None
    prev_nbss: float | None = None

    volume_total = 0.0
    value_total = 0.0
    flow_rows = 0
    positive_flow_rows = 0
    negative_flow_rows = 0
    nbss_sum = 0.0
    abs_nbss_sum = 0.0
    haka_rows = 0
    haka_sum = 0.0
    haki_sum = 0.0

    relation_counts: Counter[str] = Counter()
    activity_counts: Counter[str] = Counter()
    price_direction_counts: Counter[str] = Counter()
    flow_direction_counts: Counter[str] = Counter()
    reconstruction_counts: Counter[str] = Counter()
    digest = hashlib.sha256()

    relation_runs: list[dict[str, Any]] = []
    active_run: dict[str, Any] | None = None

    first_timestamp = str(bars[0].get("timestamp") or "")
    last_timestamp = first_timestamp
    last_close = first_close

    for i, raw in enumerate(bars):
        timestamp = str(raw.get("timestamp") or "")
        last_timestamp = timestamp
        op = _f(raw.get("open"))
        hi = _f(raw.get("high"))
        lo = _f(raw.get("low"))
        close = _f(raw.get("close"))
        volume = _f(raw.get("volume"))
        trade_value = _f(raw.get("trade_value"))
        flow_ok = bool(raw.get("flow_available", False)) and bool(raw.get("mechanism_eligible", False))
        nbss = _f(raw.get("nbss")) if flow_ok else None

        if hi is not None:
            run_hi = hi if run_hi is None else max(run_hi, hi)
        if lo is not None:
            run_lo = lo if run_lo is None else min(run_lo, lo)
        if close is not None:
            last_close = close

        price_delta_pct = _pct(close, prev_close) if prev_close not in (None, 0) else None
        path_pct = _pct(close, first_open) if first_open not in (None, 0) else None
        running_range_pct = _pct(run_hi, run_lo) if run_hi is not None and run_lo not in (None, 0) else None
        close_location = (
            (close - run_lo) / (run_hi - run_lo)
            if close is not None and run_hi is not None and run_lo is not None and run_hi > run_lo
            else 0.5 if close is not None and run_hi is not None and run_lo is not None and run_hi == run_lo
            else None
        )
        drawdown_from_running_high_pct = _pct(close, run_hi) if run_hi not in (None, 0) else None
        recovery_from_running_low_pct = _pct(close, run_lo) if run_lo not in (None, 0) else None
        fresh_running_high = hi is not None and run_hi is not None and math.isclose(hi, run_hi, rel_tol=0.0, abs_tol=1e-12)
        fresh_running_low = lo is not None and run_lo is not None and math.isclose(lo, run_lo, rel_tol=0.0, abs_tol=1e-12)

        volume_change = None if volume is None or prev_volume is None else volume - prev_volume
        value_change = None if trade_value is None or prev_value is None else trade_value - prev_value
        nbss_change = None if nbss is None or prev_nbss is None else nbss - prev_nbss

        if volume is not None:
            volume_total += volume
        if trade_value is not None:
            value_total += trade_value
        if nbss is not None:
            flow_rows += 1
            nbss_sum += nbss
            abs_nbss_sum += abs(nbss)
            if nbss > 0:
                positive_flow_rows += 1
            elif nbss < 0:
                negative_flow_rows += 1

        haka = None
        haki = None
        haka_share = None
        haki_share = None
        two_sided_effort_fraction = None
        reconstruction_status = "NOT_IN_PROVEN_HAKA_HAKI_SOURCE_SCOPE"
        if allow_haka_haki:
            rec = reconstruct_bar(raw)
            reconstruction_status = str(rec["status"])
            haka = _f(rec.get("haka"))
            haki = _f(rec.get("haki"))
            if haka is not None and haki is not None:
                haka_rows += 1
                haka_sum += haka
                haki_sum += haki
                total_effort = haka + haki
                haka_share = _safe_div(haka, total_effort)
                haki_share = _safe_div(haki, total_effort)
                two_sided_effort_fraction = _safe_div(2.0 * min(haka, haki), total_effort)
        reconstruction_counts[reconstruction_status] += 1

        relation = _flow_price_relation(nbss, price_delta_pct, flow_ok)
        activity = _activity_relation(volume_change, value_change, price_delta_pct)
        price_direction = _sign(price_delta_pct)
        flow_direction = _sign(nbss) if flow_ok else "UNKNOWN"
        relation_counts[relation] += 1
        activity_counts[activity] += 1
        price_direction_counts[price_direction] += 1
        flow_direction_counts[flow_direction] += 1

        if active_run is None or active_run["state"] != relation:
            if active_run is not None:
                active_run["end_timestamp"] = str(bars[i - 1].get("timestamp") or "")
                active_run["end_index"] = i - 1
                relation_runs.append(active_run)
            active_run = {
                "state": relation,
                "start_timestamp": timestamp,
                "end_timestamp": timestamp,
                "start_index": i,
                "end_index": i,
                "row_count": 1,
            }
        else:
            active_run["row_count"] += 1
            active_run["end_timestamp"] = timestamp
            active_run["end_index"] = i

        digest.update(
            _canon_digest_row(
                {
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
                    "price_delta_pct": price_delta_pct,
                    "path_pct": path_pct,
                    "running_range_pct": running_range_pct,
                    "close_location": close_location,
                    "drawdown_from_running_high_pct": drawdown_from_running_high_pct,
                    "recovery_from_running_low_pct": recovery_from_running_low_pct,
                    "fresh_running_high": fresh_running_high,
                    "fresh_running_low": fresh_running_low,
                    "volume_change": volume_change,
                    "value_change": value_change,
                    "nbss_change": nbss_change,
                    "haka": haka,
                    "haki": haki,
                    "haka_share": haka_share,
                    "haki_share": haki_share,
                    "two_sided_effort_fraction": two_sided_effort_fraction,
                    "relation": relation,
                    "activity_relation": activity,
                }
            )
        )

        if close is not None:
            prev_close = close
        if volume is not None:
            prev_volume = volume
        if trade_value is not None:
            prev_value = trade_value
        if nbss is not None:
            prev_nbss = nbss

    if active_run is not None:
        relation_runs.append(active_run)

    day_return_pct = _pct(last_close, first_open) if first_open not in (None, 0) else None
    flow_coverage_fraction = flow_rows / len(bars) if bars else None
    haka_coverage_fraction = haka_rows / len(bars) if bars and allow_haka_haki else None

    summary = {
        "rows": len(bars),
        "session_evidence_status": "AVAILABLE",
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "first_open": first_open,
        "first_close": first_close,
        "final_close": last_close,
        "running_high": run_hi,
        "running_low": run_lo,
        "day_return_pct": day_return_pct,
        "total_volume": volume_total,
        "total_trade_value": value_total,
        "flow_rows": flow_rows,
        "flow_coverage_fraction": flow_coverage_fraction,
        "positive_flow_rows": positive_flow_rows,
        "negative_flow_rows": negative_flow_rows,
        "nbss_sum": nbss_sum if flow_rows else None,
        "abs_nbss_sum": abs_nbss_sum if flow_rows else None,
        "haka_haki_proven_source_scope": allow_haka_haki,
        "haka_haki_rows": haka_rows,
        "haka_haki_coverage_fraction": haka_coverage_fraction,
        "haka_sum": haka_sum if haka_rows else None,
        "haki_sum": haki_sum if haka_rows else None,
        "relation_state_counts": dict(relation_counts),
        "activity_relation_counts": dict(activity_counts),
        "price_direction_counts": dict(price_direction_counts),
        "flow_direction_counts": dict(flow_direction_counts),
        "haka_haki_reconstruction_status_counts": dict(reconstruction_counts),
        "relation_transition_count": max(0, len(relation_runs) - 1),
        "first_relation_state": relation_runs[0]["state"] if relation_runs else None,
        "last_relation_state": relation_runs[-1]["state"] if relation_runs else None,
        "minute_evidence_digest_sha256": digest.hexdigest(),
    }
    return summary, relation_runs


def _write_jsonl_gz_line(fh: Any, obj: Mapping[str, Any]) -> None:
    fh.write(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")


def build_report(
    *,
    ticker_day_output: str | None = None,
    transition_output: str | None = None,
) -> dict[str, Any]:
    if v11.RESERVED_OOS in (v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B):
        raise AssertionError("RESERVED_OOS_MUST_REMAIN_OUTSIDE_DEVELOPMENT")

    sources = governed_sources_from_durable_cache()
    global_digest = hashlib.sha256()
    counters = {
        b: {"ticker_days": 0, "zero_session_ticker_days": 0, "minute_rows": 0, "relation_runs": 0}
        for b in BLOCKS
    }
    relation_counts = {b: Counter() for b in BLOCKS}
    transition_counts = {b: Counter() for b in BLOCKS}
    source_accounting: list[dict[str, Any]] = []
    first_relation_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    prior_day_by_ticker: dict[str, dict[str, Any]] = {}
    cross_day_transition_counts: Counter[str] = Counter()
    cross_day_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    td_fh = gzip.open(ticker_day_output, "wt", encoding="utf-8", newline="\n") if ticker_day_output else None
    tr_fh = gzip.open(transition_output, "wt", encoding="utf-8", newline="\n") if transition_output else None
    try:
        for src in sources:
            source = str(src["source_name"])
            block = v11._block_for(source)
            allow_haka = source == str(DEC_2024_CONTRACT["source_name"])
            if allow_haka:
                _assert_contract(src)

            src_digest = hashlib.sha256()
            src_ticker_days = 0
            src_zero_session_ticker_days = 0
            src_minute_rows = 0
            src_first_timestamp: str | None = None
            src_last_timestamp: str | None = None
            src_relation_counts: Counter[str] = Counter()

            for packet in v12r._iter_cached(source):
                bars = [dict(x) for x in packet.get("bars", [])]
                ticker = str(packet.get("ticker") or "")
                date = str(packet.get("date") or "")
                summary, runs = scan_ticker_day(bars, allow_haka_haki=allow_haka)
                src_ticker_days += 1
                src_minute_rows += int(summary["rows"])
                counters[block]["ticker_days"] += 1
                counters[block]["minute_rows"] += int(summary["rows"])
                counters[block]["relation_runs"] += len(runs)
                if int(summary["rows"]) == 0:
                    src_zero_session_ticker_days += 1
                    counters[block]["zero_session_ticker_days"] += 1

                first_ts = str(summary.get("first_timestamp") or "")
                last_ts = str(summary.get("last_timestamp") or "")
                if first_ts and src_first_timestamp is None:
                    src_first_timestamp = first_ts
                if last_ts:
                    src_last_timestamp = last_ts

                for state, n in dict(summary.get("relation_state_counts", {})).items():
                    relation_counts[block][state] += int(n)
                    src_relation_counts[state] += int(n)
                    if len(first_relation_examples[state]) < 8:
                        first_relation_examples[state].append(
                            {
                                "source": source,
                                "ticker": ticker,
                                "date": date,
                                "first_timestamp": first_ts,
                                "last_timestamp": last_ts,
                            }
                        )

                for left, right in zip(runs, runs[1:]):
                    key = f"{left['state']} -> {right['state']}"
                    transition_counts[block][key] += 1

                prev_day = prior_day_by_ticker.get(ticker)
                gap_pct = None
                cross_day_key = None
                if prev_day is not None and int(summary["rows"]) > 0:
                    gap_pct = _pct(_f(summary.get("first_open")), _f(prev_day.get("final_close")))
                    cross_day_key = f"{prev_day.get('last_relation_state')} -> {summary.get('first_relation_state')}"
                    cross_day_transition_counts[cross_day_key] += 1
                    if len(cross_day_examples[cross_day_key]) < 5:
                        cross_day_examples[cross_day_key].append(
                            {
                                "ticker": ticker,
                                "previous_source": prev_day.get("source"),
                                "previous_date": prev_day.get("date"),
                                "current_source": source,
                                "current_date": date,
                                "gap_pct": gap_pct,
                            }
                        )

                record = {
                    "source": source,
                    "block": block,
                    "ticker": ticker,
                    "date": date,
                    "previous_ticker_day": None if prev_day is None else {
                        "source": prev_day.get("source"),
                        "date": prev_day.get("date"),
                        "final_close": prev_day.get("final_close"),
                        "last_relation_state": prev_day.get("last_relation_state"),
                    },
                    "gap_from_previous_ticker_day_pct": gap_pct,
                    "cross_day_relation_transition": cross_day_key,
                    **summary,
                }
                if td_fh is not None:
                    _write_jsonl_gz_line(td_fh, record)

                for run in runs:
                    run_record = {
                        "source": source,
                        "block": block,
                        "ticker": ticker,
                        "date": date,
                        **run,
                    }
                    if tr_fh is not None:
                        _write_jsonl_gz_line(tr_fh, run_record)

                if int(summary["rows"]) > 0:
                    prior_day_by_ticker[ticker] = {
                        "source": source,
                        "date": date,
                        "final_close": summary.get("final_close"),
                        "last_relation_state": summary.get("last_relation_state"),
                    }

                packet_digest_record = {
                    "source": source,
                    "ticker": ticker,
                    "date": date,
                    "rows": summary["rows"],
                    "session_evidence_status": summary.get("session_evidence_status"),
                    "first_timestamp": first_ts,
                    "last_timestamp": last_ts,
                    "minute_evidence_digest_sha256": summary["minute_evidence_digest_sha256"],
                }
                encoded = _canon_digest_row(packet_digest_record)
                src_digest.update(encoded)
                global_digest.update(encoded)

            source_accounting.append(
                {
                    "source_name": source,
                    "block": block,
                    "source_drive_id": src.get("source_drive_id"),
                    "source_sha256": src.get("source_sha256"),
                    "generation_id": src.get("generation_id"),
                    "catalog_ticker_days": int(src.get("ticker_days", 0)),
                    "processed_ticker_days": src_ticker_days,
                    "zero_session_ticker_days": src_zero_session_ticker_days,
                    "processed_minute_rows": src_minute_rows,
                    "first_processed_timestamp": src_first_timestamp,
                    "last_processed_timestamp": src_last_timestamp,
                    "source_minute_evidence_digest_sha256": src_digest.hexdigest(),
                    "relation_state_counts": dict(src_relation_counts),
                    "haka_haki_reconstruction_enabled": allow_haka,
                    "ticker_day_accounting_pass": src_ticker_days == int(src.get("ticker_days", 0)),
                }
            )
    finally:
        if td_fh is not None:
            td_fh.close()
        if tr_fh is not None:
            tr_fh.close()

    if any(not x["ticker_day_accounting_pass"] for x in source_accounting):
        raise AssertionError("TICKER_DAY_ACCOUNTING_MISMATCH")

    total_ticker_days = sum(int(counters[b]["ticker_days"]) for b in BLOCKS)
    total_zero_session_ticker_days = sum(int(counters[b]["zero_session_ticker_days"]) for b in BLOCKS)
    total_minute_rows = sum(int(counters[b]["minute_rows"]) for b in BLOCKS)
    total_relation_runs = sum(int(counters[b]["relation_runs"]) for b in BLOCKS)

    return {
        "schema": SCHEMA,
        "status": STATUS,
        "method": "EXHAUSTIVE_EVERY_CACHED_SESSION_BAR_MINUTE_LEVEL_PRICE_X_FORMATION_CENSUS_WITH_EXACT_TEMPORAL_RELATION_RUNS",
        "data_access": "DURABLE_CACHE_ONLY_NO_RAW_REREAD",
        "scope": {
            "governed_non_oos_sources": [str(x["source_name"]) for x in sources],
            "reserved_oos_untouched": v11.RESERVED_OOS,
            "every_ticker_day_processed": True,
            "every_cached_session_bar_processed": True,
            "zero_session_ticker_days_preserved_as_unknown_evidence": True,
            "publication_slot_filter_used": False,
            "source_order_preserved": True,
        },
        "minute_read_contract": {
            "timestamp_and_provenance": True,
            "ohlc_path_range_running_high_low": True,
            "volume_and_trade_value": True,
            "validated_nbss_when_available": True,
            "separate_nfss_field": "NOT_BOUND_IN_CURRENT_DURABLE_CACHE_UNLESS_A_LATER_PROVEN_SOURCE_ADDS_IT",
            "source_bound_haka_haki": "DEC_2024_ONLY_UNDER_CURRENT_PROVEN_CONTRACT",
            "broker_participant_gross_buy_sell_net": "UNKNOWN_UNAVAILABLE_UNLESS_PROVEN_SOURCE_ADDED",
            "tick_time_and_trade": "UNKNOWN_UNAVAILABLE_UNLESS_PROVEN_SOURCE_ADDED",
            "l1_l2_orderbook_queue": "UNKNOWN_UNAVAILABLE_UNLESS_PROVEN_SOURCE_ADDED",
            "financial_issuer_sector_context": "SEPARATE_CAUSAL_LANE_WHEN_PROVEN_AND_TIME_BOUND",
            "minute_to_minute_change": True,
            "flow_price_response_non_response": True,
            "first_appearance_and_state_run_time": True,
            "cross_day_ticker_continuity": True,
            "missing_never_zero": True,
        },
        "counters": counters,
        "totals": {
            "ticker_days": total_ticker_days,
            "zero_session_ticker_days": total_zero_session_ticker_days,
            "minute_rows": total_minute_rows,
            "relation_runs": total_relation_runs,
        },
        "source_accounting": source_accounting,
        "relation_state_counts": {b: dict(relation_counts[b]) for b in BLOCKS},
        "relation_transition_counts": {b: dict(transition_counts[b]) for b in BLOCKS},
        "cross_day_relation_transition_counts": dict(cross_day_transition_counts),
        "cross_day_examples": dict(cross_day_examples),
        "first_relation_examples": dict(first_relation_examples),
        "global_minute_evidence_digest_sha256": global_digest.hexdigest(),
        "artifacts": {
            "ticker_day_summary_jsonl_gz": ticker_day_output,
            "temporal_relation_runs_jsonl_gz": transition_output,
        },
        "important_semantics": {
            "this_is_behavior_census_not_signal_formula": True,
            "no_fixed_price_or_flow_threshold_used_for_relation_states": True,
            "physical_zero_not_assumed_available_flow": True,
            "zero_session_packet_not_dropped": True,
            "haka_haki_not_used_outside_proven_source_contract": True,
            "future_outcome_not_used_to_define_current_state": True,
            "later_outcome_evaluation_not_performed_in_this_census": True,
            "reserved_oos_touched": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--ticker-day-output", required=True)
    parser.add_argument("--transition-output", required=True)
    args = parser.parse_args()
    report = build_report(
        ticker_day_output=args.ticker_day_output,
        transition_output=args.transition_output,
    )
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "totals": report["totals"],
        "counters": report["counters"],
        "global_minute_evidence_digest_sha256": report["global_minute_evidence_digest_sha256"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
