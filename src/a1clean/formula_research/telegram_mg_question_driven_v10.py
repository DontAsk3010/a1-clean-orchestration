from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from .telegram_mg_behavior_topology_v2 import _net_return_pct, _observed_step
from .telegram_mg_multihypothesis_v8 import _finite
from .telegram_mg_multihypothesis_v8c import _discover_sources_strict
from .telegram_mg_multihypothesis_v8e import _prefix_series
from .telegram_mg_replay import _is_publication_slot


QUESTIONS = (
    "Q01_PRICE_DOWN_BUYERS_STAY",
    "Q02_PRICE_DOWN_NBSS_IMPROVES",
    "Q03_PRICE_DOWN_VALUE_ABSORBED",
    "Q04_SELLING_PRESENT_PRICE_STOPS_FALLING",
    "Q05_LOW_STOPS_FALLING_FLOW_IMPROVES",
    "Q06_SIDEWAYS_MONEY_BUILDS",
    "Q07_SIDEWAYS_VOLUME_BUILDS",
    "Q08_SIDEWAYS_BUY_FLOW_BUILDS",
    "Q09_DROP_THEN_BASE_WITH_BUYING",
    "Q10_SHAKEOUT_THEN_BUYERS_RETURN",
    "Q11_BUYING_MINUTES_RISE_BEFORE_PRICE",
    "Q12_ABSORPTION_MINUTES_RISE_BEFORE_PRICE",
    "Q13_LATE_DAY_BUY_FLOW_BUILDS",
    "Q14_VALUE_RISE_PRICE_PROGRESS_WEAK",
    "Q15_VOLUME_RISE_PRICE_PROGRESS_WEAK",
    "Q16_REPEATED_POSITIVE_NBSS_NO_BREAKOUT_YET",
)

IGNITIONS = (
    "I01_VALUE_WAKE_AND_PRICE_PROGRESS",
    "I02_VOLUME_WAKE_AND_PRICE_PROGRESS",
    "I03_FLOW_WAKE_AND_PRICE_PROGRESS",
    "I04_RANGE_EXPANDS_AND_CLOSE_ACCEPTS",
    "I05_VALUE_VOLUME_FLOW_WAKE",
    "I06_ACCELERATION_AND_ACCEPTANCE",
    "I07_FRESH_INTRADAY_PROGRESS",
)


@dataclass(frozen=True)
class DayBehavior:
    date: str
    open: float
    high: float
    low: float
    close: float
    ret_pct: float
    range_pct: float
    close_location: float
    value: float
    volume: float
    nbss: float | None
    positive_nbss_bar_fraction: float | None
    negative_nbss_bar_fraction: float | None
    down_bar_positive_nbss_fraction: float | None
    sell_pressure_resilience_fraction: float | None
    buy_effort_no_progress_fraction: float | None
    late_nbss_to_value: float | None


def _med(xs: Sequence[float | None]) -> float | None:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return float(median(vals)) if vals else None


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or abs(float(b)) < 1e-12:
        return None
    return float(a) / float(b)


def _day_behavior(bars: Sequence[Mapping[str, Any]], date: str) -> DayBehavior | None:
    if not bars:
        return None
    o = _finite(bars[0].get("open")); c = _finite(bars[-1].get("close"))
    highs = [_finite(x.get("high")) for x in bars]; lows = [_finite(x.get("low")) for x in bars]
    if o is None or c is None or o <= 0 or any(x is None for x in highs + lows):
        return None
    hi = max(float(x) for x in highs if x is not None); lo = min(float(x) for x in lows if x is not None)
    if lo <= 0:
        return None
    value = sum(float(_finite(x.get("trade_value")) or 0.0) for x in bars)
    volume = sum(float(_finite(x.get("volume")) or 0.0) for x in bars)
    nbss_vals: list[float] = []
    eligible_flow = 0; pos_flow = 0; neg_flow = 0; down_pos = 0; sell_resilient = 0; buy_no_progress = 0
    prev_close: float | None = None; prev_low: float | None = None; prev_high: float | None = None
    for row in bars:
        close = _finite(row.get("close")); low = _finite(row.get("low")); high = _finite(row.get("high")); nbss = _finite(row.get("nbss"))
        flow_ok = bool(row.get("flow_available", False)) and bool(row.get("mechanism_eligible", False)) and nbss is not None
        if flow_ok:
            eligible_flow += 1; nb = float(nbss); nbss_vals.append(nb)
            pos_flow += int(nb > 0); neg_flow += int(nb < 0)
            if prev_close is not None and close is not None and float(close) <= prev_close and nb > 0:
                down_pos += 1
            if prev_close is not None and prev_low is not None and close is not None and low is not None and nb < 0 and float(close) >= prev_close and float(low) >= prev_low:
                sell_resilient += 1
            if prev_close is not None and prev_high is not None and close is not None and high is not None and nb > 0 and float(close) <= prev_close and float(high) <= prev_high:
                buy_no_progress += 1
        if close is not None: prev_close = float(close)
        if low is not None: prev_low = float(low)
        if high is not None: prev_high = float(high)
    nbss_total = sum(nbss_vals) if nbss_vals else None
    late = bars[-30:] if len(bars) >= 30 else bars
    late_value = sum(float(_finite(x.get("trade_value")) or 0.0) for x in late)
    late_nbss_vals = [float(x) for x in (_finite(r.get("nbss")) for r in late) if x is not None]
    late_nbss = sum(late_nbss_vals) if late_nbss_vals else None
    return DayBehavior(
        date=date, open=float(o), high=hi, low=lo, close=float(c),
        ret_pct=(float(c)/float(o)-1.0)*100.0,
        range_pct=(hi/lo-1.0)*100.0,
        close_location=(float(c)-lo)/(hi-lo) if hi > lo else 0.5,
        value=value, volume=volume, nbss=nbss_total,
        positive_nbss_bar_fraction=(pos_flow/eligible_flow) if eligible_flow else None,
        negative_nbss_bar_fraction=(neg_flow/eligible_flow) if eligible_flow else None,
        down_bar_positive_nbss_fraction=(down_pos/eligible_flow) if eligible_flow else None,
        sell_pressure_resilience_fraction=(sell_resilient/eligible_flow) if eligible_flow else None,
        buy_effort_no_progress_fraction=(buy_no_progress/eligible_flow) if eligible_flow else None,
        late_nbss_to_value=_ratio(late_nbss, late_value),
    )


def _question_states(history: Sequence[DayBehavior]) -> set[str]:
    if len(history) < 6:
        return set()
    prev3 = list(history[-6:-3]); last3 = list(history[-3:]); last5 = list(history[-5:])
    out: set[str] = set()
    prev_ret = _med([x.ret_pct for x in prev3]); last_ret = _med([x.ret_pct for x in last3])
    prev_value = _med([x.value for x in prev3]); last_value = _med([x.value for x in last3])
    prev_vol = _med([x.volume for x in prev3]); last_vol = _med([x.volume for x in last3])
    prev_nbss = _med([x.nbss for x in prev3]); last_nbss = _med([x.nbss for x in last3])
    prev_pos = _med([x.positive_nbss_bar_fraction for x in prev3]); last_pos = _med([x.positive_nbss_bar_fraction for x in last3])
    prev_abs = _med([x.down_bar_positive_nbss_fraction for x in prev3]); last_abs = _med([x.down_bar_positive_nbss_fraction for x in last3])
    prev_sellres = _med([x.sell_pressure_resilience_fraction for x in prev3]); last_sellres = _med([x.sell_pressure_resilience_fraction for x in last3])
    prev_late = _med([x.late_nbss_to_value for x in prev3]); last_late = _med([x.late_nbss_to_value for x in last3])
    prev_range = _med([x.range_pct for x in prev3]); last_range = _med([x.range_pct for x in last3])
    prev_loc = _med([x.close_location for x in prev3]); last_loc = _med([x.close_location for x in last3])

    down_recent = last_ret is not None and last_ret <= 0
    price_progress_weak = prev_ret is not None and last_ret is not None and last_ret <= prev_ret
    value_build = prev_value is not None and last_value is not None and last_value > prev_value
    volume_build = prev_vol is not None and last_vol is not None and last_vol > prev_vol
    nbss_improves = prev_nbss is not None and last_nbss is not None and last_nbss > prev_nbss
    pos_minutes_improve = prev_pos is not None and last_pos is not None and last_pos > prev_pos
    absorption_improves = prev_abs is not None and last_abs is not None and last_abs > prev_abs
    sell_resilience_improves = prev_sellres is not None and last_sellres is not None and last_sellres > prev_sellres
    late_flow_improves = prev_late is not None and last_late is not None and last_late > prev_late
    range_contracts = prev_range is not None and last_range is not None and last_range < prev_range
    close_accepts_better = prev_loc is not None and last_loc is not None and last_loc > prev_loc

    if down_recent and pos_minutes_improve: out.add("Q01_PRICE_DOWN_BUYERS_STAY")
    if down_recent and nbss_improves: out.add("Q02_PRICE_DOWN_NBSS_IMPROVES")
    if down_recent and value_build and absorption_improves: out.add("Q03_PRICE_DOWN_VALUE_ABSORBED")
    if down_recent and sell_resilience_improves and range_contracts: out.add("Q04_SELLING_PRESENT_PRICE_STOPS_FALLING")
    lows = [x.low for x in last3]
    if lows[1] >= lows[0] and lows[2] >= lows[1] and (nbss_improves or pos_minutes_improve): out.add("Q05_LOW_STOPS_FALLING_FLOW_IMPROVES")
    if range_contracts and value_build and abs(last_ret or 0.0) <= abs(prev_ret or 0.0): out.add("Q06_SIDEWAYS_MONEY_BUILDS")
    if range_contracts and volume_build and abs(last_ret or 0.0) <= abs(prev_ret or 0.0): out.add("Q07_SIDEWAYS_VOLUME_BUILDS")
    if range_contracts and (nbss_improves or pos_minutes_improve): out.add("Q08_SIDEWAYS_BUY_FLOW_BUILDS")
    if len(last5) == 5:
        peak = max(x.close for x in last5); trough = min(x.close for x in last5); trough_i = [x.close for x in last5].index(trough)
        drop_before_base = trough_i > 0 and trough < last5[0].close
        base_after = trough_i <= 2 and max(x.range_pct for x in last5[-2:]) <= max(x.range_pct for x in last5[:3])
        if drop_before_base and base_after and (nbss_improves or pos_minutes_improve): out.add("Q09_DROP_THEN_BASE_WITH_BUYING")
    if min(x.low for x in last3) < min(x.low for x in prev3) and close_accepts_better and (nbss_improves or absorption_improves): out.add("Q10_SHAKEOUT_THEN_BUYERS_RETURN")
    if pos_minutes_improve and price_progress_weak: out.add("Q11_BUYING_MINUTES_RISE_BEFORE_PRICE")
    if absorption_improves and price_progress_weak: out.add("Q12_ABSORPTION_MINUTES_RISE_BEFORE_PRICE")
    if late_flow_improves and price_progress_weak: out.add("Q13_LATE_DAY_BUY_FLOW_BUILDS")
    if value_build and price_progress_weak: out.add("Q14_VALUE_RISE_PRICE_PROGRESS_WEAK")
    if volume_build and price_progress_weak: out.add("Q15_VOLUME_RISE_PRICE_PROGRESS_WEAK")
    positive_nbss_days = sum(1 for x in last5 if x.nbss is not None and x.nbss > 0)
    no_breakout = last5[-1].high <= max(x.high for x in last5[:-1])
    if positive_nbss_days >= 3 and no_breakout: out.add("Q16_REPEATED_POSITIVE_NBSS_NO_BREAKOUT_YET")
    return out


def _hist_med(history_prefix: Sequence[Sequence[Mapping[str, float | None]]], index: int, key: str) -> float | None:
    vals = [float(s[index][key]) for s in history_prefix if index < len(s) and s[index] and s[index].get(key) is not None]
    return _med(vals)


def _ignition_states(current: Sequence[Mapping[str, float | None]], history_prefix: Sequence[Sequence[Mapping[str, float | None]]], index: int) -> set[str]:
    if index >= len(current) or not current[index]: return set()
    cur = current[index]
    def gt(key: str) -> bool:
        b = _hist_med(history_prefix, index, key); v = cur.get(key)
        return b is not None and v is not None and float(v) > b
    value = gt("cur_value"); volume = gt("cur_volume"); flow = gt("cur_nbss_to_value")
    path = gt("cur_path_pct"); rng = gt("cur_range_pct"); accept = gt("cur_close_location")
    vacc = gt("cur_value_accel_5v5"); volacc = gt("cur_volume_accel_5v5")
    out: set[str] = set()
    if value and path: out.add("I01_VALUE_WAKE_AND_PRICE_PROGRESS")
    if volume and path: out.add("I02_VOLUME_WAKE_AND_PRICE_PROGRESS")
    if flow and path: out.add("I03_FLOW_WAKE_AND_PRICE_PROGRESS")
    if rng and accept: out.add("I04_RANGE_EXPANDS_AND_CLOSE_ACCEPTS")
    if value and volume and flow: out.add("I05_VALUE_VOLUME_FLOW_WAKE")
    if (vacc or volacc) and path and accept: out.add("I06_ACCELERATION_AND_ACCEPTANCE")
    if path and accept and rng: out.add("I07_FRESH_INTRADAY_PROGRESS")
    return out


def _suffix(bars: Sequence[Mapping[str, Any]]) -> tuple[list[float | None], list[float | None], float | None]:
    n=len(bars); hi=[None]*(n+1); lo=[None]*(n+1)
    for i in range(n-1,-1,-1):
        h=_finite(bars[i].get("high")); l=_finite(bars[i].get("low"))
        hi[i] = hi[i+1] if h is None else (float(h) if hi[i+1] is None else max(float(h),float(hi[i+1])))
        lo[i] = lo[i+1] if l is None else (float(l) if lo[i+1] is None else min(float(l),float(lo[i+1])))
    return hi,lo,(_finite(bars[-1].get("close")) if bars else None)


def _outcome(bars: Sequence[Mapping[str, Any]], i: int, hi: Sequence[float | None], lo: Sequence[float | None], final_close: float | None, buy_fee: float, sell_fee: float) -> tuple[float,float,float] | None:
    if i+1>=len(bars): return None
    step=_observed_step(bars,i); nxt=_finite(bars[i+1].get("open"))
    if step is None or nxt is None or nxt<=0 or hi[i+1] is None or lo[i+1] is None or final_close is None: return None
    entry=float(nxt)+float(step)
    mfe=_net_return_pct(entry,max(0.0,float(hi[i+1])-float(step)),buy_fee,sell_fee)
    mae=(float(lo[i+1])/entry-1.0)*100.0
    eod=_net_return_pct(entry,max(0.0,float(final_close)-float(step)),buy_fee,sell_fee)
    return mfe,mae,eod


def _q(xs: Sequence[float], q: float) -> float | None:
    vals=sorted(float(x) for x in xs if math.isfinite(float(x)))
    if not vals:return None
    p=(len(vals)-1)*q; a=int(math.floor(p)); b=int(math.ceil(p)); w=p-a
    return vals[a] if a==b else vals[a]*(1-w)+vals[b]*w


def _metric(rows: Sequence[tuple[float,float,float]]) -> dict[str,Any]:
    mfe=[x[0] for x in rows]; mae=[x[1] for x in rows]; eod=[x[2] for x in rows]
    return {"n":len(rows),"positive_rate":sum(x>0 for x in mfe)/len(rows) if rows else None,"q25_net_mfe_pct":_q(mfe,.25),"median_net_mfe_pct":_q(mfe,.5),"q75_net_mfe_pct":_q(mfe,.75),"median_mae_pct":_q(mae,.5),"median_eod_net_pct":_q(eod,.5)}


def build_report(*,prior_days:int=10,buy_fee:float=.15,sell_fee:float=.25,min_support:int=40) -> dict[str,Any]:
    sources=[s for s in _discover_sources_strict() if not s.get("reserved_oos")]
    if len(sources)<3: raise ValueError("QUESTION_DRIVEN_REQUIRES_THREE_NON_OOS_BLOCKS")
    n=len(sources); a=max(1,n//3); b=max(a+1,(2*n)//3)
    block_names={str(s["source_name"]):("DISCOVERY" if i<a else "VALIDATION_A" if i<b else "VALIDATION_B") for i,s in enumerate(sources)}
    results={k:defaultdict(list) for k in ("DISCOVERY","VALIDATION_A","VALIDATION_B")}
    hist_day:dict[str,list[DayBehavior]]=defaultdict(list); hist_prefix:dict[str,list[list[dict[str,float|None]]]]=defaultdict(list)
    api=build_drive_api(read_write=False); ticker_days=0; slots=0
    for s in sources:
        source=str(s["source_name"]); block=block_names[source]; reader=GovernedSourceReader(api,source_name=source)
        for _ref,packet in reader.iter_packets():
            all_bars,_=packet_to_formula_bars(packet); bars=[dict(x) for x in all_bars if x.get("session_eligible")]
            if not bars: continue
            ticker_days+=1; ticker=str(packet.identity.ticker); date=str(packet.identity.trading_date)
            hd=hist_day[ticker][-prior_days:]; hp=hist_prefix[ticker][-prior_days:]; cur=_prefix_series(bars); qs=_question_states(hd); seen:set[str]=set(); shi,slo,fc=_suffix(bars)
            if qs and len(hp)>=3:
                for i,row in enumerate(bars):
                    if not _is_publication_slot(row.get("timestamp")): continue
                    slots+=1; ign=_ignition_states(cur,hp,i)
                    if not ign: continue
                    ids=[f"{q}__{g}" for q in qs for g in ign if f"{q}__{g}" not in seen]
                    if not ids: continue
                    oc=_outcome(bars,i,shi,slo,fc,buy_fee,sell_fee)
                    if oc is None: continue
                    for fid in ids: results[block][fid].append(oc); seen.add(fid)
            ds=_day_behavior(bars,date)
            if ds is not None: hist_day[ticker].append(ds); hist_day[ticker]=hist_day[ticker][-prior_days:]
            hist_prefix[ticker].append(cur); hist_prefix[ticker]=hist_prefix[ticker][-prior_days:]
    formulas=[]
    all_ids=sorted(set().union(*(set(results[k]) for k in results)))
    for fid in all_ids:
        m={k:_metric(results[k].get(fid,[])) for k in results}
        strict=all(m[k]["n"]>=min_support and (m[k]["q25_net_mfe_pct"] or -999)>0 and (m[k]["median_net_mfe_pct"] or -999)>0 for k in m)
        q,g=fid.split("__",1); formulas.append({"id":fid,"question":q,"ignition":g,"strict_cross_period_pass":strict,"metrics":m})
    formulas.sort(key=lambda r:(not r["strict_cross_period_pass"],-(r["metrics"]["VALIDATION_B"]["q25_net_mfe_pct"] or -999),-(r["metrics"]["VALIDATION_A"]["q25_net_mfe_pct"] or -999)))
    return {"schema":"A1_TELEGRAM_MG_QUESTION_DRIVEN_V10_RESULT_V1","status":"RESEARCH_ONLY_NOT_CANONICAL","question_count":len(QUESTIONS),"ignition_count":len(IGNITIONS),"formula_space":len(QUESTIONS)*len(IGNITIONS),"ticker_days_scanned":ticker_days,"publication_slots_scanned":slots,"blocks":block_names,"strict_survivor_count":sum(bool(x["strict_cross_period_pass"]) for x in formulas),"formulas":formulas,"march_oos_touched":False,"future_data_used_for_formula_state":False}


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); p.add_argument("--prior-days",type=int,default=10); p.add_argument("--buy-fee-pct",type=float,default=.15); p.add_argument("--sell-fee-pct",type=float,default=.25); p.add_argument("--min-support",type=int,default=40); a=p.parse_args()
    r=build_report(prior_days=a.prior_days,buy_fee=a.buy_fee_pct,sell_fee=a.sell_fee_pct,min_support=a.min_support); Path(a.output).write_text(json.dumps(r,indent=2,sort_keys=True),encoding="utf-8"); return 0

if __name__=="__main__": raise SystemExit(main())
