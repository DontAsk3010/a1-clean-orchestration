from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams as _CandidateParams
from .telegram_mg_replay import _is_publication_slot
from . import telegram_mg_multihypothesis_v8 as v8
from . import telegram_mg_multihypothesis_v8b as v8b
from . import telegram_mg_multihypothesis_v8c as v8c


def _params_factory() -> _CandidateParams:
    return _CandidateParams(
        effort_lookback=5,
        progress_lookback=5,
        high_lookback=5,
        recovery_lookback=5,
        low_stabilization_bars=3,
        early_checkpoint_bar=30,
        late_lift_min_bar=120,
    )


def _prefix_series(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, float | None]]:
    out: list[dict[str, float | None]] = []
    if not bars:
        return out
    first_open = v8._finite(bars[0].get("open"))
    run_hi: float | None = None
    run_lo: float | None = None
    cum_value = 0.0
    cum_volume = 0.0
    cum_nbss = 0.0
    nbss_count = 0
    values: list[float] = []
    volumes: list[float] = []
    valid_prefix = first_open is not None and first_open > 0
    for i, row in enumerate(bars):
        hi = v8._finite(row.get("high")); lo = v8._finite(row.get("low")); close = v8._finite(row.get("close"))
        if hi is None or lo is None or close is None:
            valid_prefix = False
        if hi is not None:
            run_hi = hi if run_hi is None else max(run_hi, hi)
        if lo is not None:
            run_lo = lo if run_lo is None else min(run_lo, lo)
        value = v8._finite(row.get("trade_value")) or 0.0
        volume = v8._finite(row.get("volume")) or 0.0
        values.append(value); volumes.append(volume)
        cum_value += value; cum_volume += volume
        nbss = v8._finite(row.get("nbss"))
        if nbss is not None and abs(nbss) > 0:
            cum_nbss += nbss; nbss_count += 1
        if not valid_prefix or run_hi is None or run_lo is None or close is None or first_open is None:
            out.append({})
            continue
        rng = (run_hi / run_lo - 1.0) * 100.0 if run_lo > 0 else None
        ret = (close / first_open - 1.0) * 100.0
        loc = (close - run_lo) / (run_hi - run_lo) if run_hi > run_lo else 0.5
        last5 = sum(values[max(0, i-4):i+1])
        last5v = sum(volumes[max(0, i-4):i+1])
        if i + 1 >= 10:
            prev5 = sum(values[i-9:i-4]); prev5v = sum(volumes[i-9:i-4])
        else:
            prev5 = None; prev5v = None
        nbss_total = cum_nbss if nbss_count else None
        out.append({
            "cur_path_pct": ret,
            "cur_range_pct": rng,
            "cur_close_location": loc,
            "cur_value": cum_value,
            "cur_volume": cum_volume,
            "cur_nbss": nbss_total,
            "cur_nbss_to_value": v8._safe_div(nbss_total, cum_value),
            "cur_value_accel_5v5": v8._safe_div(last5, prev5),
            "cur_volume_accel_5v5": v8._safe_div(last5v, prev5v),
        })
    return out


def _med(values: Sequence[float | None]) -> float | None:
    vals = [float(x) for x in values if x is not None]
    return float(median(vals)) if vals else None


def _event_features_fast(
    bars: Sequence[Mapping[str, Any]],
    index: int,
    hist_daily: Sequence[Any],
    hist_prefix: Sequence[Sequence[Mapping[str, float | None]]],
    current_prefix: Sequence[Mapping[str, float | None]],
) -> dict[str, float | None]:
    feat = v8._precursor_features(hist_daily)
    if index >= len(current_prefix):
        return {}
    cur = dict(current_prefix[index])
    if not cur:
        return {}
    hist_rows = [series[index] for series in hist_prefix if index < len(series) and series[index]]
    baseline = {
        "hist_prefix_value": _med([r.get("cur_value") for r in hist_rows]),
        "hist_prefix_volume": _med([r.get("cur_volume") for r in hist_rows]),
        "hist_prefix_range": _med([r.get("cur_range_pct") for r in hist_rows]),
        "hist_prefix_path": _med([r.get("cur_path_pct") for r in hist_rows]),
    }
    feat.update(cur)
    feat["ign_value_ratio"] = v8._safe_div(cur.get("cur_value"), baseline.get("hist_prefix_value"))
    feat["ign_volume_ratio"] = v8._safe_div(cur.get("cur_volume"), baseline.get("hist_prefix_volume"))
    feat["ign_range_ratio"] = v8._safe_div(cur.get("cur_range_pct"), baseline.get("hist_prefix_range"))
    path0 = cur.get("cur_path_pct"); pathb = baseline.get("hist_prefix_path")
    feat["ign_path_delta_pct"] = None if path0 is None or pathb is None else float(path0) - float(pathb)
    if hist_daily:
        prev = hist_daily[-1]
        close = v8._finite(bars[index].get("close"))
        feat["ign_vs_prev_close_pct"] = v8._pct(close, prev.close)
        feat["pre1_return_pct"] = prev.return_pct
        feat["pre1_range_pct"] = prev.range_pct
        feat["pre1_close_location"] = prev.close_location
        feat["pre1_value"] = prev.value
        feat["pre1_volume"] = prev.volume
        feat["pre1_nbss_to_value"] = v8._safe_div(prev.nbss, prev.value)
    return feat


def _load_all_events_fast(
    sources: Sequence[Mapping[str, Any]], prior_days: int, params: _CandidateParams,
    buy_fee: float, sell_fee: float,
) -> list[dict[str, Any]]:
    del params  # V8 feature discovery itself does not consume legacy MG component states.
    history_daily: dict[str, list[Any]] = defaultdict(list)
    history_prefix: dict[str, list[list[dict[str, float | None]]]] = defaultdict(list)
    out: list[dict[str, Any]] = []
    api = build_drive_api(read_write=False)
    for source_row in sources:
        source = str(source_row["source_name"])
        reader = GovernedSourceReader(api, source_name=source)
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(b) for b in all_bars if b.get("session_eligible")]
            if not bars:
                continue
            ticker = str(packet.identity.ticker); date = str(packet.identity.trading_date)
            hd = history_daily.get(ticker, [])[-prior_days:]
            hp = history_prefix.get(ticker, [])[-prior_days:]
            current_prefix = _prefix_series(bars)
            if len(hd) >= 2 and len(hp) >= 2:
                for i, bar in enumerate(bars):
                    if not _is_publication_slot(bar.get("timestamp")):
                        continue
                    feat = _event_features_fast(bars, i, hd, hp, current_prefix)
                    if not feat:
                        continue
                    row = {
                        "source": source,
                        "date": date,
                        "ticker": ticker,
                        "timestamp": bar.get("timestamp"),
                        "index": i,
                        "features": feat,
                    }
                    row.update(v8._outcome(bars, i, buy_fee, sell_fee))
                    out.append(row)
            d = v8._daily(bars, date)
            if d is not None:
                history_daily[ticker].append(d)
                history_daily[ticker] = history_daily[ticker][-prior_days:]
                history_prefix[ticker].append(current_prefix)
                history_prefix[ticker] = history_prefix[ticker][-prior_days:]
    return out


def build_report(**kwargs: Any) -> dict[str, Any]:
    v8b.CandidateParams = _params_factory  # type: ignore[assignment]
    v8b._load_all_events = _load_all_events_fast  # type: ignore[assignment]
    report = v8c.build_report(**kwargs)
    report["schema"] = "A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8E_RESULT_V1"
    report["candidate_params"] = {
        "effort_lookback": 5,
        "progress_lookback": 5,
        "high_lookback": 5,
        "recovery_lookback": 5,
        "low_stabilization_bars": 3,
        "early_checkpoint_bar": 30,
        "late_lift_min_bar": 120,
    }
    report["performance_optimization"] = {
        "prefix_stats_cached_once_per_ticker_day": True,
        "historical_prefix_recomputation_removed": True,
        "legacy_mg_component_evaluation_removed_from_v8_feature_extraction": True,
        "feature_semantics_changed": False,
        "outcome_semantics_changed": False,
    }
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--prior-days", type=int, default=10)
    p.add_argument("--buy-fee-pct", type=float, default=0.15)
    p.add_argument("--sell-fee-pct", type=float, default=0.25)
    p.add_argument("--min-support", type=int, default=40)
    p.add_argument("--min-unique-days", type=int, default=20)
    p.add_argument("--top-each", type=int, default=18)
    p.add_argument("--top-formulas", type=int, default=80)
    a = p.parse_args()
    report = build_report(
        prior_days=a.prior_days,
        buy_fee=a.buy_fee_pct,
        sell_fee=a.sell_fee_pct,
        min_support=a.min_support,
        min_unique_days=a.min_unique_days,
        top_each=a.top_each,
        top_formulas=a.top_formulas,
    )
    Path(a.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
