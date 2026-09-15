from __future__ import annotations

import argparse
import json
from pathlib import Path
from itertools import combinations
from typing import Any, Mapping, Sequence

from ..config import CANONICAL_CURRENT_FOLDER_NAME, FROZEN_CURRENT_FOLDER_DRIVE_ID
from ..google_drive import build_drive_api
from ..source_parity import FOLDER_MIME, _assert_folder, _download_bytes, _list_children
from . import telegram_mg_multihypothesis_v8b as core

RESERVED_OOS_TOKENS = ("mar 2025", "maret 2025", "maret 03-31-2025", "mar 03-31-2025")


def _discover_sources_strict() -> list[dict[str, Any]]:
    api = build_drive_api(read_write=False)
    _assert_folder(api, FROZEN_CURRENT_FOLDER_DRIVE_ID, CANONICAL_CURRENT_FOLDER_NAME)
    root = _list_children(api, FROZEN_CURRENT_FOLDER_DRIVE_ID)
    folders = {str(x["name"]): x for x in root if x.get("mimeType") == FOLDER_MIME}
    if "00_MANIFESTS" not in folders:
        raise ValueError("V8C_MANIFEST_FOLDER_MISSING")
    manifest_folder_id = str(folders["00_MANIFESTS"]["id"])
    items = _list_children(api, manifest_folder_id)
    by_name = {str(x.get("name") or ""): x for x in items if x.get("mimeType") != FOLDER_MIME}
    data_items = sorted((name, item) for name, item in by_name.items() if name.endswith("__DATA_PLANE_MANIFEST.json"))
    out = []
    ready_count = 0
    for name, item in data_items:
        obj = json.loads(_download_bytes(api, str(item["id"])).decode("utf-8"))
        if obj.get("status") != "ACCESS_READY_FOR_AI":
            continue
        ready_count += 1
        source = str(obj.get("source_name") or "")
        if not source:
            raise ValueError(f"V8C_READY_SOURCE_NAME_MISSING:{name}")
        stem = Path(source).stem
        sem_name = f"{stem}__SEMANTIC_BUNDLES_MANIFEST.json"
        sem_item = by_name.get(sem_name)
        if sem_item is None:
            raise ValueError(f"V8C_SEMANTIC_MANIFEST_MISSING:{source}:{sem_name}")
        sem = json.loads(_download_bytes(api, str(sem_item["id"])).decode("utf-8"))
        if not isinstance(sem, list) or not sem:
            raise ValueError(f"V8C_SEMANTIC_MANIFEST_EMPTY:{source}")
        dates = [str(r.get("trading_date") or "") for r in sem]
        if any(not d for d in dates):
            raise ValueError(f"V8C_SEMANTIC_DATE_MISSING:{source}")
        row_sum = sum(int(r.get("data_row_count") or 0) for r in sem)
        expected_ticker_days = int(obj.get("ticker_day_objects") or -1)
        expected_rows = int(obj.get("source_data_rows") or -1)
        if len(sem) != expected_ticker_days or row_sum != expected_rows:
            raise ValueError(f"V8C_SOURCE_ACCOUNTING_MISMATCH:{source}:SEM={len(sem)}/{row_sum}:EXPECTED={expected_ticker_days}/{expected_rows}")
        out.append({
            "source_name": source,
            "first_date": min(dates),
            "last_date": max(dates),
            "ticker_days": len(sem),
            "rows": row_sum,
            "reserved_oos": any(t in source.casefold() for t in RESERVED_OOS_TOKENS),
        })
    if len(out) != ready_count:
        raise ValueError(f"V8C_READY_SOURCE_ACCOUNTING_FAILED:{len(out)}!={ready_count}")
    out.sort(key=lambda r:(r["first_date"],r["last_date"],r["source_name"]))
    return out


def _mine_strict(events: Sequence[Mapping[str, Any]], th: Mapping[str, Sequence[tuple[str, float]]], label: Mapping[str, Any], family: str, min_support: int, min_unique_days: int, top_each: int, top_formulas: int) -> dict[str, Any]:
    rows = [e for e in events if e.get("evaluable") and e.get("net_mfe_pct") is not None]
    pos = [e for e in rows if core._winner(e, family, label)]
    neg = [e for e in rows if not core._winner(e, family, label)]
    base_precision = len(pos) / len(rows) if rows else 0.0
    psets = [core._marker_set(e, th) for e in pos]
    nsets = [core._marker_set(e, th) for e in neg]
    universe = sorted(set().union(*(psets + nsets))) if psets or nsets else []
    stats = []
    for marker in universe:
        pc = sum(marker in s for s in psets); nc = sum(marker in s for s in nsets)
        pp = pc/len(psets) if psets else 0.0; np = nc/len(nsets) if nsets else 0.0
        stats.append((marker,pc,nc,pp-np))
    pre = [x[0] for x in sorted([x for x in stats if x[0].startswith("PRE_") and x[3] > 0], key=lambda x:(x[3],x[1]), reverse=True)[:top_each]]
    ign = [x[0] for x in sorted([x for x in stats if x[0].startswith("IGN_") and x[3] > 0], key=lambda x:(x[3],x[1]), reverse=True)[:top_each]]
    candidates=[]
    def add(req: tuple[str,...]):
        pidx=[i for i,s in enumerate(psets) if all(x in s for x in req)]
        nidx=[i for i,s in enumerate(nsets) if all(x in s for x in req)]
        total=len(pidx)+len(nidx)
        if total<min_support or len(pidx)<max(3,min_support//4): return
        matched=[pos[i] for i in pidx]+[neg[i] for i in nidx]
        unique=len({(e["date"],e["ticker"]) for e in matched})
        if unique<min_unique_days: return
        precision=len(pidx)/total; recall=len(pidx)/len(psets) if psets else 0.0
        if precision<=base_precision or recall<=0: return
        candidates.append({"required":list(req),"positive":len(pidx),"negative":len(nidx),"support":total,"unique_ticker_days":unique,"precision":precision,"precision_lift_vs_family_base":precision-base_precision,"recall":recall})
    for a in pre:
        for b in ign: add((a,b))
    for a,b in combinations(pre,2):
        for c in ign: add((a,b,c))
    for a in pre:
        for b,c in combinations(ign,2): add((a,b,c))
    candidates.sort(key=lambda r:(r["precision_lift_vs_family_base"],r["precision"],r["recall"],r["unique_ticker_days"]),reverse=True)
    return {"family":family,"positive_count":len(pos),"negative_count":len(neg),"family_base_precision":base_precision,"top_pre_markers":pre,"top_ign_markers":ign,"candidates":candidates[:top_formulas]}


def build_report(**kwargs):
    core._discover_sources = _discover_sources_strict
    core._mine = _mine_strict
    report = core.build_report(**kwargs)
    report["schema"] = "A1_TELEGRAM_MG_MULTI_HYPOTHESIS_V8C_RESULT_V1"
    report["strict_source_accounting"] = True
    report["candidate_requires_precision_lift_vs_family_base"] = True
    return report


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); p.add_argument("--prior-days",type=int,default=10); p.add_argument("--buy-fee-pct",type=float,default=0.15); p.add_argument("--sell-fee-pct",type=float,default=0.25); p.add_argument("--min-support",type=int,default=40); p.add_argument("--min-unique-days",type=int,default=20); p.add_argument("--top-each",type=int,default=18); p.add_argument("--top-formulas",type=int,default=80)
    a=p.parse_args(); r=build_report(prior_days=a.prior_days,buy_fee=a.buy_fee_pct,sell_fee=a.sell_fee_pct,min_support=a.min_support,min_unique_days=a.min_unique_days,top_each=a.top_each,top_formulas=a.top_formulas); Path(a.output).write_text(json.dumps(r,indent=2,sort_keys=True),encoding="utf-8"); return 0

if __name__=="__main__": raise SystemExit(main())
