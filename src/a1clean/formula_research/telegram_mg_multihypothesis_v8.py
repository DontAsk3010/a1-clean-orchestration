from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from ..config import CANONICAL_CURRENT_FOLDER_NAME, FROZEN_CURRENT_FOLDER_DRIVE_ID
from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from ..source_parity import FOLDER_MIME, _assert_folder, _download_bytes, _list_children
from .formula_replay import packet_to_formula_bars
from .handbook_candidates import CandidateParams
from .outcome_path_quality import evaluate_outcome_path_quality
from .telegram_mg_behavior_topology_v2 import _num, _observed_step, _net_return_pct
from .telegram_mg_outcome_first_discovery_v5 import _q
from .telegram_mg_replay import evaluate_mg_packet

RESERVED_OOS_TOKENS = ("mar 2025", "maret 2025", "maret 03-31-2025", "mar 03-31-2025")


def _finite(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or abs(b) < 1e-12:
        return None
    return a / b


def _pct(a: float | None, b: float | None) -> float | None:
    r = _safe_div(a, b)
    return None if r is None else (r - 1.0) * 100.0


def _med(xs: Iterable[float | None]) -> float | None:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return float(median(vals)) if vals else None


def _discover_sources() -> list[dict[str, Any]]:
    api = build_drive_api(read_write=False)
    _assert_folder(api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    root = _list_children(api, FROZEN_CURRENT_FOLDER_DRIVE_ID)
    folders = {str(x["name"]): x for x in root if x.get("mimeType") == FOLDER_MIME}
    manifests = _list_children(api, str(folders["00_MANIFESTS"]["id"]))
    out = []
    for item in manifests:
        name = str(item.get("name") or "")
        if not name.endswith("__DATA_PLANE_MANIFEST.json"):
            continue
        raw = _download_bytes(api, str(item["id"]))
        obj = json.loads(raw.decode("utf-8"))
        if obj.get("status") != "ACCESS_READY_FOR_AI":
            continue
        source = str(obj.get("source_name") or "")
        if not source:
            continue
        try:
            reader = GovernedSourceReader(api, source_name=source)
        except Exception:
            continue
        dates = [r.trading_date for r in reader.semantic_manifest_rows]
        if not dates:
            continue
        out.append({
            "source_name": source,
            "first_date": min(dates),
            "last_date": max(dates),
            "ticker_days": len(reader.semantic_manifest_rows),
            "rows": int(reader.identity.source_data_rows),
            "reserved_oos": any(t in source.casefold() for t in RESERVED_OOS_TOKENS),
        })
    out.sort(key=lambda r: (r["first_date"], r["last_date"], r["source_name"]))
    return out


@dataclass(frozen=True)
class Daily:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float
    nbss: float | None
    nbss_coverage: float
    range_pct: float
    return_pct: float
    close_location: float
    efficiency: float


def _daily(bars: Sequence[Mapping[str, Any]], date: str) -> Daily | None:
    usable = [b for b in bars if _finite(b.get("open")) is not None and _finite(b.get("high")) is not None and _finite(b.get("low")) is not None and _finite(b.get("close")) is not None]
    if not usable:
        return None
    o = _finite(usable[0].get("open")); c = _finite(usable[-1].get("close"))
    highs = [_finite(b.get("high")) for b in usable]; lows = [_finite(b.get("low")) for b in usable]
    if o is None or c is None or o <= 0 or any(x is None for x in highs + lows):
        return None
    hi = max(float(x) for x in highs if x is not None); lo = min(float(x) for x in lows if x is not None)
    vol = sum(_finite(b.get("volume")) or 0.0 for b in usable)
    value = sum(_finite(b.get("trade_value")) or 0.0 for b in usable)
    nbss_vals = [_finite(b.get("nbss")) for b in usable if _finite(b.get("nbss")) is not None and abs(float(_finite(b.get("nbss")) or 0.0)) > 0]
    nbss = sum(nbss_vals) if nbss_vals else None
    cov = len(nbss_vals) / len(usable) if usable else 0.0
    rng = (hi / lo - 1.0) * 100.0 if lo > 0 else 0.0
    ret = (c / o - 1.0) * 100.0
    loc = (c - lo) / (hi - lo) if hi > lo else 0.5
    eff = abs(ret) / rng if rng > 1e-12 else 0.0
    return Daily(date, o, hi, lo, c, vol, value, nbss, cov, rng, ret, loc, eff)


def _prefix_stats(bars: Sequence[Mapping[str, Any]], index: int) -> dict[str, float | None]:
    rows = bars[: index + 1]
    if not rows:
        return {}
    o = _finite(rows[0].get("open")); c = _finite(rows[-1].get("close"))
    hs = [_finite(r.get("high")) for r in rows]; ls = [_finite(r.get("low")) for r in rows]
    if o is None or c is None or o <= 0 or any(x is None for x in hs + ls):
        return {}
    hi = max(float(x) for x in hs if x is not None); lo = min(float(x) for x in ls if x is not None)
    value = sum(_finite(r.get("trade_value")) or 0.0 for r in rows)
    volume = sum(_finite(r.get("volume")) or 0.0 for r in rows)
    nbss_vals = [_finite(r.get("nbss")) for r in rows if _finite(r.get("nbss")) is not None and abs(float(_finite(r.get("nbss")) or 0.0)) > 0]
    nbss = sum(nbss_vals) if nbss_vals else None
    rng = (hi / lo - 1.0) * 100.0 if lo > 0 else None
    ret = (c / o - 1.0) * 100.0
    loc = (c - lo) / (hi - lo) if hi > lo else 0.5
    last5 = rows[-5:]; prev5 = rows[-10:-5] if len(rows) >= 10 else []
    value_last5 = sum(_finite(r.get("trade_value")) or 0.0 for r in last5)
    value_prev5 = sum(_finite(r.get("trade_value")) or 0.0 for r in prev5) if prev5 else None
    volume_last5 = sum(_finite(r.get("volume")) or 0.0 for r in last5)
    volume_prev5 = sum(_finite(r.get("volume")) or 0.0 for r in prev5) if prev5 else None
    return {
        "cur_path_pct": ret,
        "cur_range_pct": rng,
        "cur_close_location": loc,
        "cur_value": value,
        "cur_volume": volume,
        "cur_nbss": nbss,
        "cur_nbss_to_value": _safe_div(nbss, value),
        "cur_value_accel_5v5": _safe_div(value_last5, value_prev5),
        "cur_volume_accel_5v5": _safe_div(volume_last5, volume_prev5),
    }


def _precursor_features(history: Sequence[Daily]) -> dict[str, float | None]:
    if len(history) < 2:
        return {}
    out: dict[str, float | None] = {}
    for w in (2, 3, 5, 8, 10):
        if len(history) < w:
            continue
        d = list(history[-w:])
        closes = [x.close for x in d]; highs = [x.high for x in d]; lows = [x.low for x in d]
        out[f"pre{w}_net_pct"] = _pct(closes[-1], closes[0])
        out[f"pre{w}_close_span_pct"] = (max(closes) / min(closes) - 1.0) * 100.0 if min(closes) > 0 else None
        out[f"pre{w}_range_pct"] = (max(highs) / min(lows) - 1.0) * 100.0 if min(lows) > 0 else None
        out[f"pre{w}_median_daily_range_pct"] = _med(x.range_pct for x in d)
        out[f"pre{w}_median_efficiency"] = _med(x.efficiency for x in d)
        out[f"pre{w}_median_close_location"] = _med(x.close_location for x in d)
        out[f"pre{w}_value_trend_ratio"] = _safe_div(_med(x.value for x in d[-max(1,w//2):]), _med(x.value for x in d[:max(1,w//2)]))
        out[f"pre{w}_volume_trend_ratio"] = _safe_div(_med(x.volume for x in d[-max(1,w//2):]), _med(x.volume for x in d[:max(1,w//2)]))
        nbss = [x.nbss for x in d if x.nbss is not None]
        out[f"pre{w}_nbss_sum"] = sum(nbss) if nbss else None
        out[f"pre{w}_nbss_to_value"] = _safe_div(sum(nbss), sum(x.value for x in d)) if nbss else None
        peak = max(closes)
        peak_i = closes.index(peak)
        out[f"pre{w}_pullback_from_peak_pct"] = (closes[-1] / peak - 1.0) * 100.0 if peak > 0 else None
        out[f"pre{w}_prior_peak_gain_pct"] = (peak / closes[0] - 1.0) * 100.0 if closes[0] > 0 else None
        post_peak = closes[peak_i:]
        out[f"pre{w}_postpeak_span_pct"] = (max(post_peak) / min(post_peak) - 1.0) * 100.0 if post_peak and min(post_peak) > 0 else None
    if len(history) >= 3:
        a,b,c = history[-3:]
        out["pre3_range_contraction"] = _safe_div(c.range_pct, a.range_pct)
        out["pre3_value_vs_price_effort"] = _safe_div(_safe_div(c.value, a.value), 1.0 + abs(c.return_pct)/100.0)
        out["pre3_low_recovery_pct"] = (c.close / min(a.low,b.low,c.low) - 1.0) * 100.0 if min(a.low,b.low,c.low) > 0 else None
    return out


def _history_prefix_baseline(history_bars: Sequence[Sequence[Mapping[str, Any]]], count: int) -> dict[str, float | None]:
    rows = []
    for bars in history_bars:
        if len(bars) < count:
            continue
        rows.append(_prefix_stats(bars, count - 1))
    return {
        "hist_prefix_value": _med(r.get("cur_value") for r in rows),
        "hist_prefix_volume": _med(r.get("cur_volume") for r in rows),
        "hist_prefix_range": _med(r.get("cur_range_pct") for r in rows),
        "hist_prefix_path": _med(r.get("cur_path_pct") for r in rows),
    }


def _outcome(bars: Sequence[Mapping[str, Any]], index: int, buy_fee: float, sell_fee: float) -> dict[str, Any]:
    if index + 1 >= len(bars):
        return {"evaluable": False}
    step = _observed_step(bars, index)
    nxt = _finite(bars[index+1].get("open"))
    if step is None or nxt is None or nxt <= 0:
        return {"evaluable": False}
    entry = nxt + float(step)
    future = bars[index+1:]
    highs = [_finite(r.get("high")) for r in future]; lows = [_finite(r.get("low")) for r in future]; closes = [_finite(r.get("close")) for r in future]
    if any(x is None for x in highs+lows+closes):
        return {"evaluable": False}
    high = max(float(x) for x in highs if x is not None); low = min(float(x) for x in lows if x is not None); final = float(closes[-1])
    high_exit = max(0.0, high-float(step)); eod_exit = max(0.0, final-float(step))
    base = {
        "evaluable": True, "entry_proxy": entry, "step_proxy": float(step),
        "net_mfe_pct": _net_return_pct(entry, high_exit, buy_fee, sell_fee),
        "mae_pct": (low/entry-1.0)*100.0,
        "eod_net_pct": _net_return_pct(entry, eod_exit, buy_fee, sell_fee),
    }
    base.update(evaluate_outcome_path_quality(bars=bars, signal_index=index, entry_proxy=entry, step_proxy=float(step), buy_fee_pct=buy_fee, sell_fee_pct=sell_fee))
    return base


def _event_features(bars: Sequence[Mapping[str, Any]], index: int, hist_daily: Sequence[Daily], hist_bars: Sequence[Sequence[Mapping[str, Any]]]) -> dict[str, float | None]:
    feat = _precursor_features(hist_daily)
    cur = _prefix_stats(bars, index)
    baseline = _history_prefix_baseline(hist_bars, index+1)
    feat.update(cur)
    feat["ign_value_ratio"] = _safe_div(cur.get("cur_value"), baseline.get("hist_prefix_value"))
    feat["ign_volume_ratio"] = _safe_div(cur.get("cur_volume"), baseline.get("hist_prefix_volume"))
    feat["ign_range_ratio"] = _safe_div(cur.get("cur_range_pct"), baseline.get("hist_prefix_range"))
    path0 = cur.get("cur_path_pct"); pathb = baseline.get("hist_prefix_path")
    feat["ign_path_delta_pct"] = None if path0 is None or pathb is None else float(path0)-float(pathb)
    if hist_daily:
        prev = hist_daily[-1]
        close = _finite(bars[index].get("close"))
        feat["ign_vs_prev_close_pct"] = _pct(close, prev.close)
        feat["pre1_return_pct"] = prev.return_pct
        feat["pre1_range_pct"] = prev.range_pct
        feat["pre1_close_location"] = prev.close_location
        feat["pre1_value"] = prev.value
        feat["pre1_volume"] = prev.volume
        feat["pre1_nbss_to_value"] = _safe_div(prev.nbss, prev.value)
    return feat


def _is_publication(mg: Mapping[str, Any]) -> bool:
    return bool(mg.get("publication_slot"))


def _source_events(source: str, *, prior_days: int, params: CandidateParams, buy_fee: float, sell_fee: float):
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source)
    history_daily: dict[str, list[Daily]] = defaultdict(list)
    history_bars: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for _ref, packet in reader.iter_packets():
        all_bars,_ = packet_to_formula_bars(packet)
        bars = [dict(b) for b in all_bars if b.get("session_eligible")]
        if not bars:
            continue
        ticker = str(packet.identity.ticker); date = str(packet.identity.trading_date)
        hd = history_daily.get(ticker, [])[-prior_days:]
        hb = history_bars.get(ticker, [])[-prior_days:]
        mgrows = evaluate_mg_packet(bars, params)
        if len(hd) >= 2 and len(hb) >= 2:
            for i, mg in enumerate(mgrows):
                if not _is_publication(mg):
                    continue
                feat = _event_features(bars, i, hd, hb)
                if not feat:
                    continue
                out = _outcome(bars, i, buy_fee, sell_fee)
                yield {"source":source,"date":date,"ticker":ticker,"timestamp":mg.get("timestamp"),"index":i,"features":feat,**out}
        d = _daily(bars,date)
        if d is not None:
            history_daily[ticker].append(d); history_daily[ticker]=history_daily[ticker][-prior_days:]
            history_bars[ticker].append(bars); history_bars[ticker]=history_bars[ticker][-prior_days:]


def _thresholds(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str,list[tuple[str,float]]],dict[str,Any]]:
    evals=[e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    mfe=[float(e["net_mfe_pct"]) for e in evals]
    positive=[x for x in mfe if x>0]
    label={"mfe_q65":_q(positive,0.65),"mfe_q80":_q(positive,0.80)}
    nums=sorted({k for e in evals for k,v in e.get("features",{}).items() if _finite(v) is not None})
    th={}
    for k in nums:
        vals=[float(e["features"][k]) for e in evals if _finite(e["features"].get(k)) is not None]
        if len(vals)<50:
            continue
        qs=[]
        for p in (0.15,0.25,0.35,0.65,0.75,0.85):
            q=_q(vals,p)
            if q is not None:
                qs.append((f"q{int(p*100):02d}",float(q)))
        th[k]=qs
    return th,label


def _winner(e: Mapping[str,Any], family: str, label: Mapping[str,Any]) -> bool:
    if not e.get("evaluable") or e.get("net_mfe_pct") is None:
        return False
    mfe=float(e["net_mfe_pct"]); q65=label.get("mfe_q65"); q80=label.get("mfe_q80")
    mae=e.get("pre_peak_mae_pct"); first=e.get("first_positive_net_offset_bars"); rr=e.get("reward_to_pre_peak_adverse"); eod=e.get("eod_net_pct")
    if family=="EXPLOSIVE": return q80 is not None and mfe>=float(q80)
    if family=="FAST_CLEAN": return q65 is not None and mfe>=float(q65) and first is not None and int(first)<=10 and mae is not None and float(mae)>=-1.5
    if family=="EFFICIENT": return q65 is not None and mfe>=float(q65) and rr is not None and float(rr)>=2.0
    if family=="RETAINED": return q65 is not None and mfe>=float(q65) and eod is not None and float(eod)>0
    raise ValueError(f"UNKNOWN_FAMILY:{family}")


def _marker_set(e: Mapping[str,Any], th: Mapping[str,Sequence[tuple[str,float]]]) -> set[str]:
    out=set(); feat=e.get("features",{})
    for k,cuts in th.items():
        v=_finite(feat.get(k))
        if v is None: continue
        for qname,cut in cuts:
            p=int(qname[1:])
            if p<=35 and v<=cut: out.add(f"{k}__LE_{qname}")
            if p>=65 and v>=cut: out.add(f"{k}__GE_{qname}")
    return out


def _group_marker(m: str) -> str:
    return "PRE" if m.startswith("pre") else "IGN"


def _mine(events: Sequence[Mapping[str,Any]], th: Mapping[str,Sequence[tuple[str,float]]], label: Mapping[str,Any], family: str, min_support:int, top_each:int, top_formulas:int):
    rows=[e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    pos=[e for e in rows if _winner(e,family,label)]; neg=[e for e in rows if not _winner(e,family,label)]
    psets=[_marker_set(e,th) for e in pos]; nsets=[_marker_set(e,th) for e in neg]
    universe=sorted(set().union(*(psets+nsets))) if psets or nsets else []
    stats=[]
    for m in universe:
        pc=sum(m in s for s in psets); nc=sum(m in s for s in nsets)
        pp=pc/len(psets) if psets else 0; np=nc/len(nsets) if nsets else 0
        if pc>=max(5,min_support//3): stats.append((m,pc,nc,pp-np))
    pre=[x for x in sorted([r for r in stats if _group_marker(r[0])=="PRE"],key=lambda x:(x[3],x[1]),reverse=True) if x[3]>0][:top_each]
    ign=[x for x in sorted([r for r in stats if _group_marker(r[0])=="IGN"],key=lambda x:(x[3],x[1]),reverse=True) if x[3]>0][:top_each]
    candidates=[]
    def score(req:tuple[str,...]):
        pm=sum(all(m in s for m in req) for s in psets); nm=sum(all(m in s for m in req) for s in nsets); total=pm+nm
        if total<min_support or pm<max(3,min_support//4): return
        precision=pm/total; recall=pm/len(psets) if psets else 0
        if precision<=0 or recall<=0: return
        candidates.append({"required":list(req),"positive":pm,"negative":nm,"support":total,"precision":precision,"recall":recall})
    pre_names=[x[0] for x in pre]; ign_names=[x[0] for x in ign]
    for a in pre_names:
        for b in ign_names: score((a,b))
    for a,b in combinations(pre_names,2):
        for c in ign_names: score((a,b,c))
    for a in pre_names:
        for b,c in combinations(ign_names,2): score((a,b,c))
    candidates.sort(key=lambda r:(r["precision"],r["recall"],r["positive"],-len(r["required"])),reverse=True)
    ded=[]; seen=set()
    for c in candidates:
        k=tuple(sorted(c["required"]))
        if k in seen: continue
        seen.add(k); ded.append(c)
        if len(ded)>=top_formulas: break
    return {"family":family,"positive_count":len(pos),"negative_count":len(neg),"top_pre_markers":[x[0] for x in pre],"top_ign_markers":[x[0] for x in ign],"candidates":ded}


def _matches(markers:set[str], req:Sequence[str])->bool: return all(x in markers for x in req)


def _metric(rows: Sequence[Mapping[str,Any]]) -> dict[str,Any]:
    vals=[float(r["net_mfe_pct"]) for r in rows if r.get("evaluable") and r.get("net_mfe_pct") is not None]
    return {"n":len(vals),"positive_rate":sum(x>0 for x in vals)/len(vals) if vals else None,"q10":_q(vals,0.10),"q25":_q(vals,0.25),"median":_q(vals,0.50),"q75":_q(vals,0.75)}


def _validate(events:Sequence[Mapping[str,Any]], th:Mapping[str,Sequence[tuple[str,float]]], mined:Mapping[str,Any], label:Mapping[str,Any], min_support:int):
    out=[]
    for i,c in enumerate(mined["candidates"],1):
        rows=[e for e in events if _matches(_marker_set(e,th),c["required"])]
        m=_metric(rows); fam=mined["family"]; hit=sum(_winner(e,fam,label) for e in rows)
        out.append({"id":f"{fam}_{i:03d}",**c,"validation":m,"family_hit_rate":hit/len(rows) if rows else None,"pass":bool(m["n"]>=min_support and m["q25"] is not None and float(m["q25"])>0 and m["median"] is not None and float(m["median"])>0)})
    return out


def build_report(*, prior_days:int,buy_fee:float,sell_fee:float,min_support:int,top_each:int,top_formulas:int)->dict[str,Any]:
    sources=_discover_sources(); usable=[s for s in sources if not s["reserved_oos"]]
    if len(usable)<3: raise ValueError("V8_NEEDS_AT_LEAST_THREE_GOVERNED_NON_OOS_SOURCES")
    n=len(usable); d_end=max(1,int(n*0.60)); v1_end=max(d_end+1,int(n*0.80)); v1_end=min(v1_end,n-1)
    discovery_sources=usable[:d_end]; val1_sources=usable[d_end:v1_end]; val2_sources=usable[v1_end:]
    params=CandidateParams()
    def load(group):
        rows=[]
        for s in group: rows.extend(_source_events(s["source_name"],prior_days=prior_days,params=params,buy_fee=buy_fee,sell_fee=sell_fee))
        return rows
    discovery=load(discovery_sources); th,label=_thresholds(discovery)
    v1=load(val1_sources); v2=load(val2_sources)
    families=("EXPLOSIVE","FAST_CLEAN","EFFICIENT","RETAINED")
    family_reports={}; strict=[]
    for fam in families:
        mined=_mine(discovery,th,label,fam,min_support,top_each,top_formulas)
        a=_validate(v1,th,mined,label,min_support); b=_validate(v2,th,mined,label,min_support)
        bmap={x["id"]:x for x in b}
        combos=[]
        for x in a:
            y=bmap.get(x["id"])
            if y is None: continue
            row={"id":x["id"],"required":x["required"],"discovery_precision":x["precision"],"discovery_recall":x["recall"],"validation_a":x["validation"],"validation_b":y["validation"],"strict_cross_period_pass":bool(x["pass"] and y["pass"])}
            combos.append(row)
            if row["strict_cross_period_pass"]: strict.append({"family":fam,**row})
        family_reports[fam]={"mining":mined,"validation":combos}
    strict.sort(key=lambda r:(min(float(r["validation_a"]["q25"]),float(r["validation_b"]["q25"])),min(float(r["validation_a"]["median"]),float(r["validation_b"]["median"])),r["discovery_precision"]),reverse=True)
    return {"schema":"A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8_RESULT_V1","status":"RESEARCH_ONLY_NOT_CANONICAL","method":"FULL_GOVERNED_CORPUS_MULTI_DAY_CONTINUOUS_PRECURSOR_PLUS_INTRADAY_IGNITION_QUANTILE_MINING","all_governed_sources":sources,"discovery_sources":discovery_sources,"validation_a_sources":val1_sources,"validation_b_sources":val2_sources,"reserved_oos_sources":[s for s in sources if s["reserved_oos"]],"counts":{"discovery_events":len(discovery),"validation_a_events":len(v1),"validation_b_events":len(v2),"feature_count":len(th)},"outcome_label_thresholds_frozen_from_discovery":label,"feature_thresholds_frozen_from_discovery":th,"families":family_reports,"strict_cross_period_pass_count":len(strict),"strict_cross_period_passed":strict[:100],"future_data_used_for_formula_state":False,"future_data_used_for_teacher_label_only":True}


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); p.add_argument("--prior-days",type=int,default=10); p.add_argument("--buy-fee-pct",type=float,default=0.15); p.add_argument("--sell-fee-pct",type=float,default=0.25); p.add_argument("--min-support",type=int,default=40); p.add_argument("--top-each",type=int,default=18); p.add_argument("--top-formulas",type=int,default=80)
    a=p.parse_args(); report=build_report(prior_days=a.prior_days,buy_fee=a.buy_fee_pct,sell_fee=a.sell_fee_pct,min_support=a.min_support,top_each=a.top_each,top_formulas=a.top_formulas); Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8"); return 0

if __name__=="__main__": raise SystemExit(main())
