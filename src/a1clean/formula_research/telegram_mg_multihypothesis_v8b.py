from __future__ import annotations

from collections import defaultdict
import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .handbook_candidates import CandidateParams
from .telegram_mg_multihypothesis_v8 import (
    _daily,
    _discover_sources,
    _event_features,
    _finite,
    _matches,
    _metric,
    _outcome,
    _q,
)
from .formula_replay import packet_to_formula_bars
from .telegram_mg_replay import evaluate_mg_packet
from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader


def _label_thresholds(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    positive = [e for e in rows if float(e["net_mfe_pct"]) > 0]
    if not positive:
        raise ValueError("V8B_NO_POSITIVE_DISCOVERY_EVENTS")
    mfe = [float(e["net_mfe_pct"]) for e in positive]
    q65 = _q(mfe, 0.65); q80 = _q(mfe, 0.80)
    strong = [e for e in positive if q65 is not None and float(e["net_mfe_pct"]) >= float(q65)]
    first = [int(e["first_positive_net_offset_bars"]) for e in strong if e.get("first_positive_net_offset_bars") is not None]
    mae = [float(e["pre_peak_mae_pct"]) for e in strong if e.get("pre_peak_mae_pct") is not None]
    rr = [float(e["reward_to_pre_peak_adverse"]) for e in strong if e.get("reward_to_pre_peak_adverse") is not None]
    retained = [
        float(e["eod_net_pct"]) / float(e["net_mfe_pct"])
        for e in strong
        if e.get("eod_net_pct") is not None and float(e["eod_net_pct"]) > 0 and float(e["net_mfe_pct"]) > 0
    ]
    return {
        "mfe_q65": q65,
        "mfe_q80": q80,
        "strong_first_positive_q50_bars": int(round(_q(first, 0.50))) if first else None,
        "strong_pre_peak_mae_q50": _q(mae, 0.50) if mae else None,
        "strong_reward_to_adverse_q50": _q(rr, 0.50) if rr else None,
        "strong_retained_fraction_q50": _q(retained, 0.50) if retained else None,
    }


def _winner(e: Mapping[str, Any], family: str, t: Mapping[str, Any]) -> bool:
    if not e.get("evaluable") or e.get("net_mfe_pct") is None:
        return False
    mfe = float(e["net_mfe_pct"]); q65 = t.get("mfe_q65"); q80 = t.get("mfe_q80")
    if family == "EXPLOSIVE":
        return q80 is not None and mfe >= float(q80)
    if q65 is None or mfe < float(q65):
        return False
    if family == "FAST_CLEAN":
        first = e.get("first_positive_net_offset_bars"); mae = e.get("pre_peak_mae_pct")
        f50 = t.get("strong_first_positive_q50_bars"); m50 = t.get("strong_pre_peak_mae_q50")
        return first is not None and f50 is not None and int(first) <= int(f50) and mae is not None and m50 is not None and float(mae) >= float(m50)
    if family == "EFFICIENT":
        rr = e.get("reward_to_pre_peak_adverse"); r50 = t.get("strong_reward_to_adverse_q50")
        return rr is not None and r50 is not None and float(rr) >= float(r50)
    if family == "RETAINED":
        eod = e.get("eod_net_pct"); r50 = t.get("strong_retained_fraction_q50")
        frac = float(eod) / mfe if eod is not None and mfe > 0 else None
        return eod is not None and float(eod) > 0 and frac is not None and r50 is not None and frac >= float(r50)
    raise ValueError(f"V8B_UNKNOWN_FAMILY:{family}")


def _feature_thresholds(events: Sequence[Mapping[str, Any]]) -> dict[str, list[tuple[str, float]]]:
    rows = [e for e in events if e.get("evaluable")]
    keys = sorted({k for e in rows for k, v in e.get("features", {}).items() if _finite(v) is not None})
    out: dict[str, list[tuple[str, float]]] = {}
    for k in keys:
        vals = [float(e["features"][k]) for e in rows if _finite(e["features"].get(k)) is not None]
        if len(vals) < 100:
            continue
        cuts = []
        for p in (0.15, 0.25, 0.35, 0.65, 0.75, 0.85):
            q = _q(vals, p)
            if q is not None:
                cuts.append((f"q{int(p*100):02d}", float(q)))
        out[k] = cuts
    return out


def _cut(th: Mapping[str, Sequence[tuple[str, float]]], feature: str, qname: str) -> float | None:
    for name, value in th.get(feature, ()):
        if name == qname:
            return float(value)
    return None


def _le(feat: Mapping[str, Any], th: Mapping[str, Sequence[tuple[str, float]]], k: str, q: str) -> bool:
    v = _finite(feat.get(k)); c = _cut(th, k, q)
    return v is not None and c is not None and v <= c


def _ge(feat: Mapping[str, Any], th: Mapping[str, Sequence[tuple[str, float]]], k: str, q: str) -> bool:
    v = _finite(feat.get(k)); c = _cut(th, k, q)
    return v is not None and c is not None and v >= c


def _marker_set(e: Mapping[str, Any], th: Mapping[str, Sequence[tuple[str, float]]]) -> set[str]:
    feat = e.get("features", {})
    out: set[str] = set()
    for k, cuts in th.items():
        v = _finite(feat.get(k))
        if v is None:
            continue
        for qname, cut in cuts:
            p = int(qname[1:])
            if p <= 35 and v <= cut:
                out.add(f"PRE_{k}__LE_{qname}" if k.startswith("pre") else f"IGN_{k}__LE_{qname}")
            elif p >= 65 and v >= cut:
                out.add(f"PRE_{k}__GE_{qname}" if k.startswith("pre") else f"IGN_{k}__GE_{qname}")

    # Named precursor hypotheses. Thresholds are quantiles frozen from discovery,
    # so these names express market logic without inventing fixed percentage cutoffs.
    if _le(feat, th, "pre3_close_span_pct", "q25"):
        out.add("PRE_SIDEWAYS_3D")
    if _le(feat, th, "pre5_close_span_pct", "q25"):
        out.add("PRE_SIDEWAYS_5D")
    if _le(feat, th, "pre8_close_span_pct", "q25"):
        out.add("PRE_SIDEWAYS_8D")
    if _le(feat, th, "pre3_range_contraction", "q25"):
        out.add("PRE_RANGE_COMPRESSION")
    if _ge(feat, th, "pre5_value_trend_ratio", "q75") and _le(feat, th, "pre5_close_span_pct", "q35"):
        out.add("PRE_VALUE_BUILD_SIDEWAYS")
    if _ge(feat, th, "pre5_volume_trend_ratio", "q75") and _le(feat, th, "pre5_close_span_pct", "q35"):
        out.add("PRE_VOLUME_BUILD_SIDEWAYS")
    if _ge(feat, th, "pre5_nbss_to_value", "q75") and _le(feat, th, "pre5_close_span_pct", "q35"):
        out.add("PRE_FLOW_BUILD_SIDEWAYS")
    if _ge(feat, th, "pre5_prior_peak_gain_pct", "q75") and _le(feat, th, "pre5_pullback_from_peak_pct", "q25") and _le(feat, th, "pre3_close_span_pct", "q35"):
        out.add("PRE_RISE_PULLBACK_BASE_5D")
    if _ge(feat, th, "pre8_prior_peak_gain_pct", "q75") and _le(feat, th, "pre8_pullback_from_peak_pct", "q25") and _le(feat, th, "pre3_close_span_pct", "q35"):
        out.add("PRE_RISE_PULLBACK_BASE_8D")
    if _ge(feat, th, "pre3_low_recovery_pct", "q75") and _le(feat, th, "pre3_close_span_pct", "q35"):
        out.add("PRE_SHAKEOUT_RECOVERY_BASE")
    if _ge(feat, th, "pre3_value_vs_price_effort", "q75") and _le(feat, th, "pre3_close_span_pct", "q35"):
        out.add("PRE_HIGH_EFFORT_LOW_PROGRESS")

    # Named current-day ignition hypotheses.
    if _ge(feat, th, "ign_value_ratio", "q75"):
        out.add("IGN_VALUE_WAKE")
    if _ge(feat, th, "ign_volume_ratio", "q75"):
        out.add("IGN_VOLUME_WAKE")
    if _ge(feat, th, "ign_range_ratio", "q75"):
        out.add("IGN_RANGE_EXPANSION")
    if _ge(feat, th, "ign_path_delta_pct", "q75"):
        out.add("IGN_PATH_OUTPERFORMANCE")
    if _ge(feat, th, "cur_value_accel_5v5", "q75"):
        out.add("IGN_VALUE_ACCELERATION")
    if _ge(feat, th, "cur_volume_accel_5v5", "q75"):
        out.add("IGN_VOLUME_ACCELERATION")
    if _ge(feat, th, "cur_close_location", "q75"):
        out.add("IGN_HIGH_ACCEPTANCE")
    if _ge(feat, th, "cur_nbss_to_value", "q75"):
        out.add("IGN_FLOW_EXPANSION")
    return out


def _load_all_events(sources: Sequence[Mapping[str, Any]], prior_days: int, params: CandidateParams, buy_fee: float, sell_fee: float) -> list[dict[str, Any]]:
    history_daily: dict[str, list[Any]] = defaultdict(list)
    history_bars: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
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
            hb = history_bars.get(ticker, [])[-prior_days:]
            mgrows = evaluate_mg_packet(bars, params)
            if len(hd) >= 2 and len(hb) >= 2:
                for i, mg in enumerate(mgrows):
                    if not mg.get("publication_slot"):
                        continue
                    feat = _event_features(bars, i, hd, hb)
                    if not feat:
                        continue
                    row = {"source": source, "date": date, "ticker": ticker, "timestamp": mg.get("timestamp"), "index": i, "features": feat}
                    row.update(_outcome(bars, i, buy_fee, sell_fee))
                    out.append(row)
            d = _daily(bars, date)
            if d is not None:
                history_daily[ticker].append(d); history_daily[ticker] = history_daily[ticker][-prior_days:]
                history_bars[ticker].append(bars); history_bars[ticker] = history_bars[ticker][-prior_days:]
    return out


def _mine(events: Sequence[Mapping[str, Any]], th: Mapping[str, Sequence[tuple[str, float]]], label: Mapping[str, Any], family: str, min_support: int, min_unique_days: int, top_each: int, top_formulas: int) -> dict[str, Any]:
    rows = [e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    pos = [e for e in rows if _winner(e, family, label)]; neg = [e for e in rows if not _winner(e, family, label)]
    psets = [_marker_set(e, th) for e in pos]; nsets = [_marker_set(e, th) for e in neg]
    universe = sorted(set().union(*(psets + nsets))) if psets or nsets else []
    stats = []
    for m in universe:
        pc = sum(m in s for s in psets); nc = sum(m in s for s in nsets)
        pp = pc / len(psets) if psets else 0.0; np = nc / len(nsets) if nsets else 0.0
        stats.append((m, pc, nc, pp - np))
    pre = [x[0] for x in sorted([x for x in stats if x[0].startswith("PRE_") and x[3] > 0], key=lambda x:(x[3],x[1]), reverse=True)[:top_each]]
    ign = [x[0] for x in sorted([x for x in stats if x[0].startswith("IGN_") and x[3] > 0], key=lambda x:(x[3],x[1]), reverse=True)[:top_each]]
    candidates = []
    def add(req: tuple[str, ...]):
        pidx = [i for i,s in enumerate(psets) if all(x in s for x in req)]
        nidx = [i for i,s in enumerate(nsets) if all(x in s for x in req)]
        total = len(pidx)+len(nidx)
        if total < min_support or len(pidx) < max(3, min_support//4): return
        matched_rows = [pos[i] for i in pidx] + [neg[i] for i in nidx]
        unique = len({(e["date"],e["ticker"]) for e in matched_rows})
        if unique < min_unique_days: return
        precision = len(pidx)/total; recall = len(pidx)/len(psets) if psets else 0.0
        candidates.append({"required":list(req),"positive":len(pidx),"negative":len(nidx),"support":total,"unique_ticker_days":unique,"precision":precision,"recall":recall})
    for a in pre:
        for b in ign: add((a,b))
    for a,b in __import__("itertools").combinations(pre,2):
        for c in ign: add((a,b,c))
    for a in pre:
        for b,c in __import__("itertools").combinations(ign,2): add((a,b,c))
    candidates.sort(key=lambda r:(r["precision"],r["recall"],r["unique_ticker_days"],r["positive"]), reverse=True)
    return {"family":family,"positive_count":len(pos),"negative_count":len(neg),"top_pre_markers":pre,"top_ign_markers":ign,"candidates":candidates[:top_formulas]}


def _validate(events: Sequence[Mapping[str, Any]], th: Mapping[str, Sequence[tuple[str, float]]], mined: Mapping[str, Any], min_support: int, min_unique_days: int) -> list[dict[str, Any]]:
    out = []
    for i,c in enumerate(mined["candidates"],1):
        rows = [e for e in events if _matches(_marker_set(e,th),c["required"])]
        m = _metric(rows); unique = len({(e["date"],e["ticker"]) for e in rows})
        passed = bool(m["n"] >= min_support and unique >= min_unique_days and m["q25"] is not None and float(m["q25"]) > 0 and m["median"] is not None and float(m["median"]) > 0)
        out.append({"id":f"{mined['family']}_{i:03d}",**c,"validation":m,"validation_unique_ticker_days":unique,"pass":passed})
    return out


def build_report(*, prior_days:int,buy_fee:float,sell_fee:float,min_support:int,min_unique_days:int,top_each:int,top_formulas:int)->dict[str,Any]:
    sources = _discover_sources(); failed = [s for s in sources if not s.get("source_name")]
    if failed: raise ValueError("V8B_SOURCE_DISCOVERY_INCOMPLETE")
    usable = [s for s in sources if not s["reserved_oos"]]
    if len(usable) < 3: raise ValueError("V8B_NEEDS_AT_LEAST_THREE_NON_OOS_SOURCES")
    n=len(usable); d_end=max(1,int(n*0.60)); v1_end=max(d_end+1,int(n*0.80)); v1_end=min(v1_end,n-1)
    disc_src=usable[:d_end]; va_src=usable[d_end:v1_end]; vb_src=usable[v1_end:]
    params=CandidateParams(); all_events=_load_all_events(usable,prior_days,params,buy_fee,sell_fee)
    disc_names={s["source_name"] for s in disc_src}; va_names={s["source_name"] for s in va_src}; vb_names={s["source_name"] for s in vb_src}
    discovery=[e for e in all_events if e["source"] in disc_names]; va=[e for e in all_events if e["source"] in va_names]; vb=[e for e in all_events if e["source"] in vb_names]
    th=_feature_thresholds(discovery); label=_label_thresholds(discovery)
    families=("EXPLOSIVE","FAST_CLEAN","EFFICIENT","RETAINED")
    reports={}; strict=[]
    for fam in families:
        mined=_mine(discovery,th,label,fam,min_support,min_unique_days,top_each,top_formulas)
        a=_validate(va,th,mined,min_support,min_unique_days); b=_validate(vb,th,mined,min_support,min_unique_days); bm={x["id"]:x for x in b}
        val=[]
        for x in a:
            y=bm.get(x["id"])
            if y is None: continue
            row={"id":x["id"],"required":x["required"],"discovery_precision":x["precision"],"discovery_recall":x["recall"],"discovery_unique_ticker_days":x["unique_ticker_days"],"validation_a":x["validation"],"validation_a_unique_ticker_days":x["validation_unique_ticker_days"],"validation_b":y["validation"],"validation_b_unique_ticker_days":y["validation_unique_ticker_days"],"strict_cross_period_pass":bool(x["pass"] and y["pass"])}
            val.append(row)
            if row["strict_cross_period_pass"]: strict.append({"family":fam,**row})
        reports[fam]={"mining":mined,"validation":val}
    strict.sort(key=lambda r:(min(float(r["validation_a"]["q25"]),float(r["validation_b"]["q25"])),min(float(r["validation_a"]["median"]),float(r["validation_b"]["median"])),r["discovery_precision"]),reverse=True)
    return {"schema":"A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8B_RESULT_V1","status":"RESEARCH_ONLY_NOT_CANONICAL","method":"ALL_GOVERNED_NON_OOS_CHRONOLOGICAL_CONTINUOUS_MULTI_DAY_PRECURSOR_PLUS_INTRADAY_IGNITION_WITH_NAMED_HYPOTHESIS_COMBINATIONS","all_governed_sources":sources,"discovery_sources":disc_src,"validation_a_sources":va_src,"validation_b_sources":vb_src,"reserved_oos_sources":[s for s in sources if s["reserved_oos"]],"counts":{"all_events":len(all_events),"discovery_events":len(discovery),"validation_a_events":len(va),"validation_b_events":len(vb),"continuous_feature_count":len(th)},"outcome_label_thresholds_frozen_from_discovery":label,"feature_thresholds_frozen_from_discovery":th,"families":reports,"strict_cross_period_pass_count":len(strict),"strict_cross_period_passed":strict[:100],"future_data_used_for_formula_state":False,"future_data_used_for_teacher_label_only":True,"cross_source_history_continuity":True}


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); p.add_argument("--prior-days",type=int,default=10); p.add_argument("--buy-fee-pct",type=float,default=0.15); p.add_argument("--sell-fee-pct",type=float,default=0.25); p.add_argument("--min-support",type=int,default=40); p.add_argument("--min-unique-days",type=int,default=20); p.add_argument("--top-each",type=int,default=18); p.add_argument("--top-formulas",type=int,default=80)
    a=p.parse_args(); r=build_report(prior_days=a.prior_days,buy_fee=a.buy_fee_pct,sell_fee=a.sell_fee_pct,min_support=a.min_support,min_unique_days=a.min_unique_days,top_each=a.top_each,top_formulas=a.top_formulas); Path(a.output).write_text(json.dumps(r,indent=2,sort_keys=True),encoding="utf-8"); return 0

if __name__=="__main__": raise SystemExit(main())
