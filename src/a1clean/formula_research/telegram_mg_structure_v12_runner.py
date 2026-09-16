from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..google_drive import build_drive_api
from ..pattern_discovery.source_reader import GovernedSourceReader
from .formula_replay import packet_to_formula_bars
from . import telegram_mg_question_driven_v10 as v10
from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12 as v12
from .telegram_mg_replay import _is_publication_slot

CACHE_SCHEMA = "A1_MG_NORMALIZED_BAR_CACHE_V1"
BLOCKS = ("DISCOVERY", "VALIDATION_A", "VALIDATION_B")


def _cache_root() -> Path:
    raw = os.environ.get("A1_MG_FEATURE_CACHE_ROOT")
    root = Path(raw) if raw else (Path.home() / ".a1clean" / "mg_normalized_cache_v1")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_path(source: str) -> Path:
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return _cache_root() / f"{key}.jsonl.gz"


def _meta_path(source: str) -> Path:
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    return _cache_root() / f"{key}.meta.json"


def _meta_ok(source: str, src: Mapping[str, Any]) -> bool:
    mp = _meta_path(source); cp = _cache_path(source)
    if not mp.is_file() or not cp.is_file():
        return False
    try:
        obj = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (
        obj.get("schema") == CACHE_SCHEMA
        and obj.get("source_name") == source
        and int(obj.get("ticker_days", -1)) == int(src.get("ticker_days", -2))
        and int(obj.get("rows", -1)) == int(src.get("rows", -2))
        and obj.get("complete") is True
    )


def _build_cache(source: str, src: Mapping[str, Any]) -> dict[str, Any]:
    api = build_drive_api(read_write=False)
    reader = GovernedSourceReader(api, source_name=source)
    target = _cache_path(source)
    tmp = target.with_suffix(target.suffix + ".tmp")
    count = 0
    rows = 0
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        for _ref, packet in reader.iter_packets():
            all_bars, _ = packet_to_formula_bars(packet)
            bars = [dict(x) for x in all_bars if x.get("session_eligible")]
            obj = {
                "ticker": str(packet.identity.ticker),
                "date": str(packet.identity.trading_date),
                "bars": bars,
            }
            fh.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
            count += 1
            rows += len(bars)
    tmp.replace(target)
    meta = {
        "schema": CACHE_SCHEMA,
        "source_name": source,
        "source_drive_id": reader.identity.source_drive_id,
        "source_sha256": reader.identity.source_sha256,
        "generation_id": reader.identity.generation_id,
        "semantic_manifest_fingerprint": reader.identity.semantic_manifest_fingerprint,
        "ticker_days": int(src["ticker_days"]),
        "rows": int(src["rows"]),
        "cached_ticker_days": count,
        "cached_session_rows": rows,
        "complete": count == int(src["ticker_days"]),
    }
    _meta_path(source).write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    if not meta["complete"]:
        raise RuntimeError(f"V12_CACHE_INCOMPLETE:{source}:{count}!={src['ticker_days']}")
    return meta


def _ensure_cache(sources: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reused: list[str] = []
    built: list[str] = []
    for src in sources:
        source = str(src["source_name"])
        if _meta_ok(source, src):
            reused.append(source)
        else:
            _build_cache(source, src)
            built.append(source)
    return {"reused_sources": reused, "built_sources": built, "cache_root": str(_cache_root())}


def _iter_cached(source: str) -> Iterable[dict[str, Any]]:
    with gzip.open(_cache_path(source), "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _q(xs: Sequence[float], q: float) -> float | None:
    vals = sorted(float(x) for x in xs if math.isfinite(float(x)))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    p = (len(vals) - 1) * q
    lo = int(math.floor(p)); hi = int(math.ceil(p)); w = p - lo
    return vals[lo] if lo == hi else vals[lo] * (1.0 - w) + vals[hi] * w


def _metric(rows: Sequence[tuple[float, float, float]]) -> dict[str, Any]:
    mfe=[x[0] for x in rows]; mae=[x[1] for x in rows]; eod=[x[2] for x in rows]
    return {
        "n": len(rows),
        "positive_net_mfe_rate": (sum(x > 0 for x in mfe) / len(mfe)) if mfe else None,
        "q10_net_mfe_pct": _q(mfe,.10), "q25_net_mfe_pct": _q(mfe,.25),
        "median_net_mfe_pct": _q(mfe,.50), "q75_net_mfe_pct": _q(mfe,.75), "q90_net_mfe_pct": _q(mfe,.90),
        "median_mae_pct": _q(mae,.50), "median_eod_net_pct": _q(eod,.50),
    }


def _strict(metrics: Mapping[str, Mapping[str, Any]], min_support: int) -> bool:
    for b in BLOCKS:
        m=metrics[b]
        if int(m["n"]) < min_support: return False
        if m["q25_net_mfe_pct"] is None or float(m["q25_net_mfe_pct"]) <= 0: return False
        if m["median_net_mfe_pct"] is None or float(m["median_net_mfe_pct"]) <= 0: return False
    return True


def _allowed(pre: set[str], fid: str) -> bool:
    mapping = {
        "K02_SHAKEOUT_RECLAIM_RETEST_CONTINUE": "J02_SHAKEOUT_FLOW_RECLAIM_HOLD",
        "K03_FLOW_LEAD_PERSIST_PRICE_CATCHUP": "J03_FLOW_LEADS_DELAYED_PRICE_RESPONSE",
        "K04_EFFORT_NO_PROGRESS_THEN_EFFICIENCY_FLIP": "J04_EFFORT_RESPONSE_FLIP",
        "K05_COMPRESSION_HIGHER_LOW_BREAK_RETEST": "J05_HIGHER_LOW_COMPRESSION_EXPANSION",
        "K06_RISE_PULLBACK_BASE_REACCEL": "J06_RISE_PULLBACK_BASE_REACCELERATION",
        "K07_SELL_EXHAUSTION_CONTROL_TRANSFER": "J07_SELL_EXHAUSTION_BUY_TURN",
    }
    need = mapping.get(fid)
    return True if need is None else need in pre


def _enrich_snapshot(snap: dict[str, Any], row: Mapping[str, Any], prev_snap: Mapping[str, Any] | None, prev_row: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(snap)
    flow = out.get("nbss_to_value")
    out["sell_pressure_present"] = flow is not None and float(flow) < 0.0
    prev_path = None if prev_snap is None else prev_snap.get("path")
    cur_path = out.get("path")
    prev_flow = None if prev_snap is None else prev_snap.get("nbss_to_value")
    out["sell_response_weakens"] = (
        cur_path is not None and prev_path is not None and float(cur_path) >= float(prev_path)
        and ((flow is not None and float(flow) < 0.0) or (prev_flow is not None and float(prev_flow) < 0.0))
    )
    cur_low = row.get("low"); prev_low = None if prev_row is None else prev_row.get("low")
    out["low_stabilized"] = cur_low is not None and prev_low is not None and float(cur_low) >= float(prev_low)
    return out


def build_report(*, prior_days: int=10, buy_fee: float=.15, sell_fee: float=.25, min_support: int=40) -> dict[str, Any]:
    sources=v11._ordered_governed_sources()
    cache_status=_ensure_cache(sources)
    results={b:defaultdict(list) for b in BLOCKS}
    examples={b:defaultdict(list) for b in BLOCKS}
    counters={b:{"ticker_days":0,"publication_slots":0,"signals":0} for b in BLOCKS}
    hist_day: dict[str,list[v10.DayBehavior]]=defaultdict(list)
    hist_prefix: dict[str,list[list[dict[str,float|None]]]]=defaultdict(list)

    for src in sources:
        source=str(src["source_name"]); block=v11._block_for(source)
        for packet in _iter_cached(source):
            bars=[dict(x) for x in packet["bars"]]
            if not bars: continue
            ticker=str(packet["ticker"]); date=str(packet["date"])
            counters[block]["ticker_days"] += 1
            hd=hist_day[ticker][-prior_days:]; hp=hist_prefix[ticker][-prior_days:]
            cur=v11._prefix_series(bars)
            pre=v11._preconditions(hd)
            hi,lo,fc=v10._suffix(bars)
            states={fid:v12.SequenceState() for fid in v12.FORMULAS if _allowed(pre,fid)}
            seen:set[str]=set()
            prev_snap:dict[str,Any]|None=None; prev_row:dict[str,Any]|None=None
            if states and len(hp)>=3:
                for i,row in enumerate(bars):
                    if not _is_publication_slot(row.get("timestamp")): continue
                    counters[block]["publication_slots"] += 1
                    base=v11._snapshot(cur,hp,i)
                    if not base: continue
                    snap=_enrich_snapshot(base,row,prev_snap,prev_row)
                    for fid,st in states.items():
                        if fid in seen: continue
                        if v12.advance(fid,st,snap):
                            oc=v10._outcome(bars,i,hi,lo,fc,buy_fee,sell_fee)
                            if oc is not None:
                                results[block][fid].append(oc); counters[block]["signals"] += 1; seen.add(fid)
                                if len(examples[block][fid])<5:
                                    examples[block][fid].append({"source":source,"ticker":ticker,"date":date,"timestamp":row.get("timestamp"),"signal_close":row.get("close"),"path_pct":snap.get("path"),"net_mfe_pct":oc[0],"mae_pct":oc[1],"eod_net_pct":oc[2]})
                    prev_snap=snap; prev_row=row
            d=v10._day_behavior(bars,date)
            if d is not None:
                hist_day[ticker].append(d); hist_day[ticker]=hist_day[ticker][-prior_days:]
                hist_prefix[ticker].append(cur); hist_prefix[ticker]=hist_prefix[ticker][-prior_days:]

    formulas=[]
    for fid in v12.FORMULAS:
        metrics={b:_metric(results[b].get(fid,[])) for b in BLOCKS}
        strict=_strict(metrics,min_support)
        worst_q25=min(float(metrics[b]["q25_net_mfe_pct"] if metrics[b]["q25_net_mfe_pct"] is not None else -999.0) for b in BLOCKS)
        worst_med=min(float(metrics[b]["median_net_mfe_pct"] if metrics[b]["median_net_mfe_pct"] is not None else -999.0) for b in BLOCKS)
        formulas.append({"id":fid,"strict_cross_period_pass":strict,"worst_block_q25_net_mfe_pct":worst_q25,"worst_block_median_net_mfe_pct":worst_med,"metrics":metrics,"examples":{b:examples[b].get(fid,[]) for b in BLOCKS}})
    formulas.sort(key=lambda r:(bool(r["strict_cross_period_pass"]),float(r["worst_block_q25_net_mfe_pct"]),float(r["worst_block_median_net_mfe_pct"])),reverse=True)
    survivors=[x for x in formulas if x["strict_cross_period_pass"]]
    return {
        "schema":"A1_TELEGRAM_MG_STRUCTURE_V12_RESULT_V1",
        "status":"RESEARCH_ONLY_NOT_CANONICAL",
        "method":"STRUCTURE_REWRITE_ONLY_FROM_V11_PRIMITIVES_WITH_DURABLE_NORMALIZED_BAR_CACHE",
        "cache":cache_status,
        "formula_count":len(v12.FORMULAS),
        "formulas_tested":list(v12.FORMULAS),
        "governed_blocks":{"DISCOVERY":list(v11.DISCOVERY),"VALIDATION_A":list(v11.VALIDATION_A),"VALIDATION_B":list(v11.VALIDATION_B),"RESERVED_OOS_UNTOUCHED":v11.RESERVED_OOS},
        "execution":{"buy_fee_pct":buy_fee,"sell_fee_pct":sell_fee},
        "min_support":min_support,
        "counters":counters,
        "strict_survivor_count":len(survivors),
        "strict_survivors":survivors,
        "ranked_formulas":formulas,
        "future_data_used_for_formula_state":False,
        "future_data_used_for_outcome_evaluation_only":True,
        "march_2025_reserved_oos_touched":False,
    }


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); p.add_argument("--prior-days",type=int,default=10); p.add_argument("--buy-fee-pct",type=float,default=.15); p.add_argument("--sell-fee-pct",type=float,default=.25); p.add_argument("--min-support",type=int,default=40); a=p.parse_args()
    report=build_report(prior_days=a.prior_days,buy_fee=a.buy_fee_pct,sell_fee=a.sell_fee_pct,min_support=a.min_support)
    Path(a.output).write_text(json.dumps(report,indent=2,sort_keys=True),encoding="utf-8")
    return 0

if __name__=="__main__": raise SystemExit(main())
