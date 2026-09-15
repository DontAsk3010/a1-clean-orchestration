from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams
from .mg_frozen_candidate_replay import replay_pack
from .telegram_mg_behavior_topology_v2 import _net_return_pct, _num, _observed_step
from .telegram_mg_outcome_first_discovery_v5 import _outcome_at


def _first_target_hit(
    bars: Sequence[Mapping[str, Any]], signal_index: int, target: float | None,
    *, entry_proxy: float | None, step_proxy: float | None,
    buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    if target is None or entry_proxy is None or step_proxy is None:
        return {"hit": False, "hit_time": None, "net_pct": None}
    for row in bars[signal_index + 1 :]:
        high = _num(row.get("high"))
        if high is None:
            continue
        if float(high) >= float(target):
            exit_proxy = max(0.0, float(target) - float(step_proxy))
            return {
                "hit": True,
                "hit_time": str(row.get("timestamp") or "")[11:16],
                "net_pct": _net_return_pct(
                    float(entry_proxy), exit_proxy, buy_fee_pct, sell_fee_pct
                ),
            }
    return {"hit": False, "hit_time": None, "net_pct": None}


def _enrich_row(
    row: Mapping[str, Any], *, bars: Sequence[Mapping[str, Any]], signal_index: int,
    buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    outcome = _outcome_at(bars, signal_index, buy_fee_pct, sell_fee_pct)
    entry_proxy = _num(outcome.get("entry_proxy"))
    step_proxy = _num(outcome.get("step_proxy"))
    tp1 = _num(row.get("tp1"))
    tp2 = _num(row.get("tp2"))
    tp1_result = _first_target_hit(
        bars, signal_index, tp1, entry_proxy=entry_proxy, step_proxy=step_proxy,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    )
    tp2_result = _first_target_hit(
        bars, signal_index, tp2, entry_proxy=entry_proxy, step_proxy=step_proxy,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    )
    return {
        **dict(row),
        "entry_proxy": entry_proxy,
        "tp1_hit": tp1_result["hit"],
        "tp1_hit_time": tp1_result["hit_time"],
        "tp1_net_pct": tp1_result["net_pct"],
        "tp2_hit": tp2_result["hit"],
        "tp2_hit_time": tp2_result["hit_time"],
        "tp2_net_pct": tp2_result["net_pct"],
        "net_max_pct": outcome.get("net_mfe_pct"),
        "mae_pct": outcome.get("mae_pct"),
        "eod_net_pct": outcome.get("eod_net_pct"),
        "evaluable": bool(outcome.get("evaluable")),
    }


def build_report(
    pack: Mapping[str, Any], *, source_names: Sequence[str], params: CandidateParams,
    prior_window: int, buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    base = replay_pack(
        pack, source_names=source_names, params=params, prior_window=prior_window,
        buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
    )
    telegram_days = base.get("telegram_5min_days") or {}
    needed: set[tuple[str, str]] = set()
    for date, snapshots in telegram_days.items():
        for snap in snapshots:
            for row in snap.get("rows") or []:
                needed.add((str(date), str(row.get("ticker"))))

    bars_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for source_name in source_names:
        api = build_drive_api(read_write=False)
        reader = GovernedSourceReader(api, source_name=source_name)
        for _manifest_row, packet in reader.iter_packets():
            key = (str(packet.identity.trading_date), str(packet.identity.ticker))
            if key not in needed:
                continue
            all_bars, _ = packet_to_formula_bars(packet)
            bars_by_key[key] = [b for b in all_bars if b.get("session_eligible")]

    enriched_days: dict[str, list[dict[str, Any]]] = {}
    for date, snapshots in telegram_days.items():
        out_snaps: list[dict[str, Any]] = []
        for snap in snapshots:
            timestamp = str(snap.get("timestamp") or "")
            out_rows: list[dict[str, Any]] = []
            for row in snap.get("rows") or []:
                ticker = str(row.get("ticker"))
                bars = bars_by_key.get((str(date), ticker), [])
                signal_index = next(
                    (i for i, bar in enumerate(bars) if str(bar.get("timestamp") or "") == timestamp),
                    None,
                )
                if signal_index is None:
                    out_rows.append({**dict(row), "evaluable": False, "error": "SNAPSHOT_BAR_NOT_FOUND"})
                    continue
                out_rows.append(_enrich_row(
                    row, bars=bars, signal_index=signal_index,
                    buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
                ))
            out_snaps.append({
                **dict(snap),
                "rows": out_rows,
                "empty": len(out_rows) == 0,
            })
        enriched_days[str(date)] = out_snaps

    return {
        **base,
        "schema": "A1_TELEGRAM_MG_5MIN_SNAPSHOT_OUTCOME_REPLAY_V1",
        "telegram_5min_days": enriched_days,
        "telegram_replay_columns": [
            "CODE", "PRICE", "CHG%", "TP-1", "TP1 HIT@", "P/L TP1",
            "TP-2", "TP2 HIT@", "P/L TP2", "NET MAX P/L",
        ],
        "target_hit_semantics": "FIRST_FUTURE_INTRADAY_HIGH_AT_OR_ABOVE_DYNAMIC_TARGET",
        "target_pl_semantics": "NET_RETURN_FROM_NEXT_BAR_OPEN_PLUS_STEP_TO_TARGET_MINUS_STEP_AFTER_FEES",
        "persistence_policy": "REPEAT_TICKER_EVERY_5MIN_WHILE_CURRENT_CRITERIA_REMAIN_VALID",
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="a1clean-mg-telegram-snapshot-outcome-replay")
    p.add_argument("--pack", required=True)
    p.add_argument("--source-name", action="append", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--prior-window", type=int, default=2)
    p.add_argument("--buy-fee-pct", type=float, required=True)
    p.add_argument("--sell-fee-pct", type=float, required=True)
    p.add_argument("--effort-lookback", type=int, required=True)
    p.add_argument("--progress-lookback", type=int, required=True)
    p.add_argument("--high-lookback", type=int, required=True)
    p.add_argument("--recovery-lookback", type=int, required=True)
    p.add_argument("--low-stabilization-bars", type=int, required=True)
    p.add_argument("--early-checkpoint-bar", type=int, required=True)
    p.add_argument("--late-lift-min-bar", type=int, required=True)
    a = p.parse_args(argv)
    params = CandidateParams(
        effort_lookback=a.effort_lookback,
        progress_lookback=a.progress_lookback,
        high_lookback=a.high_lookback,
        recovery_lookback=a.recovery_lookback,
        low_stabilization_bars=a.low_stabilization_bars,
        early_checkpoint_bar=a.early_checkpoint_bar,
        late_lift_min_bar=a.late_lift_min_bar,
    )
    pack = json.loads(Path(a.pack).read_text(encoding="utf-8"))
    report = build_report(
        pack, source_names=a.source_name, params=params,
        prior_window=a.prior_window, buy_fee_pct=a.buy_fee_pct,
        sell_fee_pct=a.sell_fee_pct,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "pass": True,
        "telegram_day_count": len(report.get("telegram_5min_days") or {}),
        "telegram_snapshot_count": sum(len(v) for v in (report.get("telegram_5min_days") or {}).values()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
