from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .corpus_translate import _FolderStore
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams, TRUE
from .telegram_mg_clean_v2_study import (
    BASE_VARIANT,
    CLEAN_PROFILES,
    PRIOR_WINDOW,
    _enrich_context,
    _profile_matches,
)
from .telegram_mg_multiday_context_study import DayRecord, _history_context, _num
from .telegram_mg_precision_study import PRECISION_VARIANTS, _candidate_features, _variant_matches
from .telegram_mg_replay import evaluate_mg_packet


def _quantile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not clean:
        return None
    if q <= 0:
        return clean[0]
    if q >= 1:
        return clean[-1]
    pos = (len(clean) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return clean[lo]
    w = pos - lo
    return clean[lo] * (1.0 - w) + clean[hi] * w


def _observed_price_step(bars: Sequence[Mapping[str, Any]], index: int, lookback: int = 30) -> float | None:
    start = max(0, index - lookback + 1)
    values: list[float] = []
    for row in bars[start : index + 1]:
        for key in ("open", "high", "low", "close"):
            value = _num(row.get(key))
            if value is not None and value > 0:
                values.append(float(value))
    unique = sorted(set(values))
    diffs = [b - a for a, b in zip(unique, unique[1:]) if b - a > 1e-9]
    if not diffs:
        return None
    return min(diffs)


def _future_max_reward_pct(bars: Sequence[Mapping[str, Any]], index: int, entry: float) -> float | None:
    highs = [_num(row.get("high")) for row in bars[index + 1 :]]
    highs = [float(v) for v in highs if v is not None]
    if not highs or entry <= 0:
        return None
    return (max(highs) / entry - 1.0) * 100.0


def _execution_net(entry: float, exit_price: float, shares: int, buy_fee_pct: float, sell_fee_pct: float) -> dict[str, float]:
    buy_value = entry * shares
    sell_value = exit_price * shares
    buy_fee = buy_value * buy_fee_pct / 100.0
    sell_fee = sell_value * sell_fee_pct / 100.0
    gross = sell_value - buy_value
    net = gross - buy_fee - sell_fee
    return {
        "buy_value": buy_value,
        "sell_value": sell_value,
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "gross_pl": gross,
        "net_pl": net,
    }


def _candidate_at(
    *,
    bars: Sequence[Mapping[str, Any]],
    index: int,
    mg: Mapping[str, Any],
    ticker_history: Mapping[str, DayRecord],
    prior_dates: Sequence[str],
    p5_rule: Mapping[str, Any],
    lookback: int,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not mg.get("publication_slot"):
        return None
    if mg["variants"].get("MG_B_PATH_VALUE") != TRUE:
        return None
    p5_features = _candidate_features(bars, index, lookback=lookback)
    if not _variant_matches(p5_features, p5_rule):
        return None
    base_context = _history_context(
        bars=bars,
        index=index,
        history_by_date=ticker_history,
        prior_dates=prior_dates,
    )
    if base_context is None:
        return None
    context = _enrich_context(
        base_context,
        bars=bars,
        index=index,
        ticker_history=ticker_history,
        prior_dates=prior_dates,
    )
    if context is None:
        return None
    if not _profile_matches(context, CLEAN_PROFILES["ARP_STRONG"]):
        return None
    return context, p5_features


def build_profit_qualified_report(
    *,
    source_names: Sequence[str],
    trading_date: str,
    params: CandidateParams,
    capital_per_entry: float,
    buy_fee_pct: float,
    sell_fee_pct: float,
    tp1_quantile: float,
    tp2_quantile: float,
) -> dict[str, Any]:
    params.validate()
    if len(source_names) < 2:
        raise ValueError("AT_LEAST_TWO_CHRONOLOGICAL_SOURCES_REQUIRED")
    if not (0 < tp1_quantile < tp2_quantile < 1):
        raise ValueError("TARGET_QUANTILES_MUST_ASCEND_INSIDE_0_1")
    if capital_per_entry <= 0:
        raise ValueError("POSITIVE_CAPITAL_REQUIRED")

    p5_rule = PRECISION_VARIANTS[BASE_VARIANT]
    lookback = max(params.effort_lookback, params.progress_lookback, params.high_lookback)
    history: dict[str, dict[str, DayRecord]] = defaultdict(dict)
    completed_market_dates: list[str] = []
    seen_market_dates: set[str] = set()
    current_market_date: str | None = None
    training_rewards_pct: list[float] = []
    training_examples = 0
    target_packets: dict[str, list[dict[str, Any]]] = {}
    target_histories: dict[str, dict[str, DayRecord]] = {}
    scanned_packets = 0
    target_seen = False

    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        stop_source = False
        for _manifest_row, packet in reader.iter_packets():
            date = str(packet.identity.trading_date)
            if target_seen and date > trading_date:
                stop_source = True
                break

            if current_market_date is None:
                current_market_date = date
            elif date != current_market_date:
                if current_market_date not in seen_market_dates:
                    completed_market_dates.append(current_market_date)
                    seen_market_dates.add(current_market_date)
                current_market_date = date
                keep_dates = set(completed_market_dates[-(PRIOR_WINDOW + 2) :])
                for ticker in list(history):
                    history[ticker] = {d: rec for d, rec in history[ticker].items() if d in keep_dates}
                    if not history[ticker]:
                        del history[ticker]

            all_bars, _mapping = packet_to_formula_bars(packet)
            bars = [bar for bar in all_bars if bar["session_eligible"]]
            scanned_packets += 1
            ticker = str(packet.identity.ticker)

            if date == trading_date:
                target_seen = True
                if bars:
                    target_packets[ticker] = bars
                    target_histories[ticker] = dict(history.get(ticker, {}))
                continue
            if date > trading_date:
                stop_source = True
                break
            if not bars:
                continue

            # Development/training uses only dates strictly before the target date.
            if len(completed_market_dates) >= PRIOR_WINDOW:
                prior_dates = completed_market_dates[-PRIOR_WINDOW:]
                mg_rows = evaluate_mg_packet(bars, params)
                for i, mg in enumerate(mg_rows):
                    matched = _candidate_at(
                        bars=bars,
                        index=i,
                        mg=mg,
                        ticker_history=history.get(ticker, {}),
                        prior_dates=prior_dates,
                        p5_rule=p5_rule,
                        lookback=lookback,
                    )
                    if matched is None:
                        continue
                    entry = _num(bars[i].get("close"))
                    if entry is None or entry <= 0:
                        break
                    reward = _future_max_reward_pct(bars, i, entry)
                    if reward is not None:
                        training_rewards_pct.append(reward)
                        training_examples += 1
                    break

            history.setdefault(ticker, {})[date] = DayRecord(
                trading_date=date,
                bars=tuple(dict(bar) for bar in bars),
            )
        if stop_source:
            break

    if not target_packets:
        raise ValueError(f"TARGET_DATE_NOT_FOUND:{trading_date}")
    if len(completed_market_dates) < PRIOR_WINDOW:
        raise ValueError("PRIOR_MARKET_DATES_UNAVAILABLE")
    if len(training_rewards_pct) < 20:
        raise ValueError(f"INSUFFICIENT_PRETARGET_TRAINING_EXAMPLES:{len(training_rewards_pct)}")

    q1 = _quantile(training_rewards_pct, tp1_quantile)
    q2 = _quantile(training_rewards_pct, tp2_quantile)
    if q1 is None or q2 is None or q1 <= 0 or q2 <= q1:
        raise ValueError(f"INVALID_EMPIRICAL_TARGETS:{q1}:{q2}")

    prior_dates = completed_market_dates[-PRIOR_WINDOW:]
    slots_all: set[str] = set()
    slot_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trades: list[dict[str, Any]] = []
    rejected_profit_room: list[dict[str, Any]] = []

    for ticker, bars in target_packets.items():
        mg_rows = evaluate_mg_packet(bars, params)
        first_candidate_done = False
        for i, mg in enumerate(mg_rows):
            if mg.get("publication_slot"):
                slots_all.add(str(mg.get("timestamp")))
            if first_candidate_done:
                continue
            matched = _candidate_at(
                bars=bars,
                index=i,
                mg=mg,
                ticker_history=target_histories.get(ticker, {}),
                prior_dates=prior_dates,
                p5_rule=p5_rule,
                lookback=lookback,
            )
            if matched is None:
                continue
            first_candidate_done = True
            context, p5_features = matched
            signal_price = _num(bars[i].get("close"))
            if signal_price is None or signal_price <= 0:
                continue
            step = _observed_price_step(bars, i)
            if step is None or step <= 0:
                continue
            entry_proxy = signal_price + step
            tp1 = signal_price * (1.0 + q1 / 100.0)
            tp2 = signal_price * (1.0 + q2 / 100.0)
            tp1_exit_proxy = max(signal_price, tp1 - step)
            tp2_exit_proxy = max(tp1_exit_proxy, tp2 - step)
            lots = int(capital_per_entry // (entry_proxy * 100.0))
            if lots < 1:
                continue
            shares = lots * 100
            net_tp1 = _execution_net(entry_proxy, tp1_exit_proxy, shares, buy_fee_pct, sell_fee_pct)["net_pl"]
            net_tp2 = _execution_net(entry_proxy, tp2_exit_proxy, shares, buy_fee_pct, sell_fee_pct)["net_pl"]
            room_pass = bool(net_tp1 > 0 and net_tp2 > net_tp1)
            timestamp = str(mg.get("timestamp"))
            previous_close = _num(context.get("previous_regular_close"))
            chg_pct = ((signal_price / previous_close - 1.0) * 100.0) if previous_close and previous_close > 0 else None

            base = {
                "TIME": timestamp,
                "CODE": ticker,
                "PRICE": signal_price,
                "CHG%": chg_pct,
                "TP-1": tp1,
                "TP-2": tp2,
                "entry_proxy_haka": entry_proxy,
                "observed_price_step_proxy": step,
                "lots": lots,
                "shares": shares,
                "capital_limit": capital_per_entry,
                "estimated_buy_value": entry_proxy * shares,
                "tp1_net_if_filled": net_tp1,
                "tp2_net_if_filled": net_tp2,
                "profit_room_pass": room_pass,
                "context": context,
                "p5_features": p5_features,
            }
            if not room_pass:
                rejected_profit_room.append(base)
                continue

            slot_rows[timestamp].append({k: base[k] for k in ("CODE", "PRICE", "CHG%", "TP-1", "TP-2")})

            tp1_hit_time = None
            tp2_hit_time = None
            close_time = None
            final_close = signal_price
            for row in bars[i + 1 :]:
                high = _num(row.get("high"))
                close = _num(row.get("close"))
                ts = str(row.get("timestamp"))
                if close is not None:
                    final_close = close
                    close_time = ts
                if high is not None and tp1_hit_time is None and high >= tp1:
                    tp1_hit_time = ts
                if high is not None and tp2_hit_time is None and high >= tp2:
                    tp2_hit_time = ts

            lot1 = lots // 2
            lot2 = lots - lot1
            if lot1 == 0:
                lot1 = lots
                lot2 = 0
            total = {"buy_value": 0.0, "sell_value": 0.0, "buy_fee": 0.0, "sell_fee": 0.0, "gross_pl": 0.0, "net_pl": 0.0}
            exit_legs: list[dict[str, Any]] = []

            def add_leg(leg_lots: int, exit_price: float, reason: str, exit_time: str | None) -> None:
                if leg_lots <= 0:
                    return
                leg_shares = leg_lots * 100
                result = _execution_net(entry_proxy, exit_price, leg_shares, buy_fee_pct, sell_fee_pct)
                for key in total:
                    total[key] += result[key]
                exit_legs.append({"lots": leg_lots, "shares": leg_shares, "exit_price_proxy_haki": exit_price, "exit_time": exit_time, "reason": reason, **result})

            if tp1_hit_time is not None:
                add_leg(lot1, tp1_exit_proxy, "TP1", tp1_hit_time)
                if lot2 > 0:
                    if tp2_hit_time is not None:
                        add_leg(lot2, tp2_exit_proxy, "TP2", tp2_hit_time)
                    else:
                        close_exit = max(0.0, final_close - step)
                        add_leg(lot2, close_exit, "EOD_AFTER_TP1", close_time)
            else:
                close_exit = max(0.0, final_close - step)
                add_leg(lots, close_exit, "EOD_NO_TP1", close_time)

            trades.append({
                **base,
                "tp1_hit_time": tp1_hit_time,
                "tp2_hit_time": tp2_hit_time,
                "exit_legs": exit_legs,
                "gross_pl": total["gross_pl"],
                "net_pl": total["net_pl"],
                "result": "PROFIT" if total["net_pl"] > 0 else ("BREAKEVEN" if abs(total["net_pl"]) < 1e-9 else "LOSS"),
            })

    slots: list[dict[str, Any]] = []
    previous_codes: set[str] = set()
    seen_codes: set[str] = set()
    for timestamp in sorted(slots_all):
        rows = sorted(slot_rows.get(timestamp, []), key=lambda row: str(row["CODE"]))
        current_codes = {str(row["CODE"]) for row in rows}
        slots.append({
            "as_of": timestamp,
            "display_time": datetime.fromisoformat(timestamp).strftime("%H:%M"),
            "candidate_count": len(rows),
            "new_codes": sorted(current_codes - seen_codes),
            "continued_codes": sorted(current_codes & previous_codes),
            "returned_codes": sorted((current_codes - previous_codes) & seen_codes),
            "dropped_codes": sorted(previous_codes - current_codes),
            "telegram_zero_match_render": "========" if not rows else None,
            "rows": rows,
        })
        seen_codes.update(current_codes)
        previous_codes = current_codes

    net_total = sum(float(row["net_pl"]) for row in trades)
    gross_total = sum(float(row["gross_pl"]) for row in trades)
    return {
        "schema": "A1_TELEGRAM_MG_PROFIT_QUALIFIED_V1",
        "status": "RESEARCH_CANDIDATE_NOT_CANONICAL",
        "trading_date": trading_date,
        "formula": "MG_PROFIT_QUALIFIED_V1",
        "base_behavior_candidate": "MG_CLEAN_W2_ARP_STRONG",
        "training_policy": "ONLY_TRADING_DATES_STRICTLY_BEFORE_TARGET_DATE",
        "training_example_count": training_examples,
        "training_reward_distribution_pct": {
            "q25": _quantile(training_rewards_pct, 0.25),
            "median": _quantile(training_rewards_pct, 0.50),
            "q75": _quantile(training_rewards_pct, 0.75),
            "selected_tp1_quantile": tp1_quantile,
            "selected_tp1_reward_pct": q1,
            "selected_tp2_quantile": tp2_quantile,
            "selected_tp2_reward_pct": q2,
        },
        "execution_profile": {
            "capital_per_entry": capital_per_entry,
            "buy_fee_pct": buy_fee_pct,
            "sell_fee_pct": sell_fee_pct,
            "historical_haka_proxy": "SIGNAL_CLOSE_PLUS_CAUSAL_OBSERVED_PRICE_STEP",
            "historical_haki_proxy": "TARGET_OR_EOD_PRICE_MINUS_CAUSAL_OBSERVED_PRICE_STEP",
            "exit_policy": "HALF_AT_TP1__REMAINDER_AT_TP2_ELSE_EOD__ALL_EOD_IF_NO_TP1",
            "note": "Historical RAW has no proven contemporaneous BBO/order-book; proxies are deliberately explicit and are not claimed as actual fills.",
        },
        "target_ticker_count": len(target_packets),
        "scanned_source_packets": scanned_packets,
        "slot_count": len(slots),
        "slots": slots,
        "trades": sorted(trades, key=lambda row: (str(row["TIME"]), str(row["CODE"]))),
        "rejected_profit_room": sorted(rejected_profit_room, key=lambda row: (str(row["TIME"]), str(row["CODE"]))),
        "summary": {
            "published_trade_count": len(trades),
            "profit_count": sum(int(row["result"] == "PROFIT") for row in trades),
            "loss_count": sum(int(row["result"] == "LOSS") for row in trades),
            "breakeven_count": sum(int(row["result"] == "BREAKEVEN") for row in trades),
            "rejected_profit_room_count": len(rejected_profit_room),
            "gross_pl_total": gross_total,
            "net_pl_total": net_total,
            "capital_limit_sum": sum(float(row["capital_limit"]) for row in trades),
            "actual_estimated_buy_value_sum": sum(float(row["estimated_buy_value"]) for row in trades),
        },
        "future_data_used_for_signal_state": False,
        "future_data_used_for_target_training": "PRIOR_DATES_ONLY",
        "future_data_used_for_trade_outcome_audit": True,
        "h_plus_1_used": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="a1clean-telegram-mg-profit-qualified-v1")
    parser.add_argument("--source-name", action="append", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--drive-output-folder-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--capital-per-entry", type=float, default=5_000_000.0)
    parser.add_argument("--buy-fee-pct", type=float, default=0.15)
    parser.add_argument("--sell-fee-pct", type=float, default=0.25)
    parser.add_argument("--tp1-quantile", type=float, default=0.25)
    parser.add_argument("--tp2-quantile", type=float, default=0.50)
    parser.add_argument("--effort-lookback", type=int, required=True)
    parser.add_argument("--progress-lookback", type=int, required=True)
    parser.add_argument("--high-lookback", type=int, required=True)
    parser.add_argument("--recovery-lookback", type=int, required=True)
    parser.add_argument("--low-stabilization-bars", type=int, required=True)
    parser.add_argument("--early-checkpoint-bar", type=int, required=True)
    parser.add_argument("--late-lift-min-bar", type=int, required=True)
    args = parser.parse_args(argv)

    params = CandidateParams(
        effort_lookback=args.effort_lookback,
        progress_lookback=args.progress_lookback,
        high_lookback=args.high_lookback,
        recovery_lookback=args.recovery_lookback,
        low_stabilization_bars=args.low_stabilization_bars,
        early_checkpoint_bar=args.early_checkpoint_bar,
        late_lift_min_bar=args.late_lift_min_bar,
    )
    report = build_profit_qualified_report(
        source_names=args.source_name,
        trading_date=args.trading_date,
        params=params,
        capital_per_entry=args.capital_per_entry,
        buy_fee_pct=args.buy_fee_pct,
        sell_fee_pct=args.sell_fee_pct,
        tp1_quantile=args.tp1_quantile,
        tp2_quantile=args.tp2_quantile,
    )
    report = {**report, "request_id": args.request_id, "software_revision": args.software_revision}
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    writer = build_drive_api(read_write=True)
    store = _FolderStore(writer, args.drive_output_folder_id)
    safe_request = "".join(ch for ch in args.request_id if ch.isalnum() or ch in "-_")
    uploaded = store.upsert_json(name=f"TELEGRAM_MG_PROFIT_QUALIFIED_V1__{safe_request}.json", obj=report)
    print(json.dumps({"pass": True, "report": report, "drive_artifact": uploaded}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
