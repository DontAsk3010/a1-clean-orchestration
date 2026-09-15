from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .telegram_mg_behavior_topology_v2 import _net_return_pct, _num
from .telegram_mg_outcome_first_discovery_v5 import _outcome_at


def _target_result(
    bars: Sequence[Mapping[str, Any]], signal_index: int, target: float | None,
    *, entry_proxy: float | None, step_proxy: float | None,
    buy_fee_pct: float, sell_fee_pct: float,
) -> dict[str, Any]:
    if target is None or entry_proxy is None or step_proxy is None:
        return {"hit": False, "hit_time": None, "net_pct": None}
    for bar in bars[signal_index + 1:]:
        high = _num(bar.get("high"))
        if high is None or float(high) < float(target):
            continue
        exit_proxy = max(0.0, float(target) - float(step_proxy))
        return {
            "hit": True,
            "hit_time": str(bar.get("timestamp") or "")[11:16],
            "net_pct": _net_return_pct(float(entry_proxy), exit_proxy, buy_fee_pct, sell_fee_pct),
        }
    return {"hit": False, "hit_time": None, "net_pct": None}


def build_report(request: Mapping[str, Any]) -> dict[str, Any]:
    source_name = str(request["source_name"])
    target_date = str(request["target_date"])
    snapshots = list(request.get("target_snapshots") or [])
    observed_slots = [str(x) for x in request.get("observed_slots") or []]
    buy_fee_pct = float(request["execution"]["buy_fee_pct"])
    sell_fee_pct = float(request["execution"]["sell_fee_pct"])

    needed_tickers = sorted({
        str(row["ticker"])
        for snap in snapshots
        for row in (snap.get("rows") or [])
    })
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source_name)
    index_by_key = {
        (str(ref.trading_date), str(ref.ticker)): ref.manifest_index
        for ref in reader.semantic_manifest_rows
    }

    bars_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for ticker in needed_tickers:
        idx = index_by_key.get((target_date, ticker))
        if idx is None:
            raise ValueError(f"TARGET_PACKET_NOT_FOUND:{target_date}:{ticker}")
        packet = reader.load_packet(idx)
        all_bars, _ = packet_to_formula_bars(packet)
        bars_by_ticker[ticker] = [b for b in all_bars if b.get("session_eligible")]

    snapshot_map = {str(s["time"]): s for s in snapshots}
    output_slots: list[dict[str, Any]] = []
    for slot in observed_slots:
        base = snapshot_map.get(slot, {"time": slot, "rows": []})
        out_rows: list[dict[str, Any]] = []
        for row in base.get("rows") or []:
            ticker = str(row["ticker"])
            bars = bars_by_ticker[ticker]
            timestamp = f"{target_date} {slot}:00"
            signal_index = next(
                (i for i, bar in enumerate(bars) if str(bar.get("timestamp") or "") == timestamp),
                None,
            )
            if signal_index is None:
                raise ValueError(f"SNAPSHOT_BAR_NOT_FOUND:{target_date}:{ticker}:{slot}")
            outcome = _outcome_at(bars, signal_index, buy_fee_pct, sell_fee_pct)
            entry_proxy = _num(outcome.get("entry_proxy"))
            step_proxy = _num(outcome.get("step_proxy"))
            tp1 = _num(row.get("tp1"))
            tp2 = _num(row.get("tp2"))
            tp1_result = _target_result(
                bars, signal_index, tp1, entry_proxy=entry_proxy, step_proxy=step_proxy,
                buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            )
            tp2_result = _target_result(
                bars, signal_index, tp2, entry_proxy=entry_proxy, step_proxy=step_proxy,
                buy_fee_pct=buy_fee_pct, sell_fee_pct=sell_fee_pct,
            )
            out_rows.append({
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
            })
        output_slots.append({"time": slot, "rows": out_rows, "empty": not out_rows})

    return {
        "schema": "A1_TELEGRAM_MG_TARGETED_5MIN_OUTCOME_REPLAY_V1",
        "source_name": source_name,
        "target_date": target_date,
        "base_artifact_run_id": request.get("base_artifact_run_id"),
        "slots": output_slots,
        "columns": [
            "CODE", "PRICE", "CHG%", "TP-1", "TP1 HIT@", "P/L TP1",
            "TP-2", "TP2 HIT@", "P/L TP2", "NET MAX P/L",
        ],
        "persistence_policy": "REPEAT_TICKER_EVERY_5MIN_WHILE_CURRENT_CRITERIA_REMAIN_VALID",
        "future_data_used_only_for_replay_outcomes": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--request", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args(argv)
    request = json.loads(Path(a.request).read_text(encoding="utf-8"))
    report = build_report(request)
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pass": True, "slot_count": len(report["slots"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
