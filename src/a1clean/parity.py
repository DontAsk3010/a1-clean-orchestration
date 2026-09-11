from __future__ import annotations

from pathlib import Path
import hashlib, json

STABLE_SOURCE_KEYS=(
    "generation_id","source_name","source_drive_id","source_size_bytes","source_sha256",
    "physical_access_ready","physical_shard_count","sampling_used","filtering_used",
    "behavior_labels_created","unknown_field_drop_allowed","text_encoding","delimiter",
    "header_fields","all_fields_preserved","routing","source_data_rows","routed_rows",
    "unresolved_routing_rows","unique_trading_dates","unique_tickers","ticker_day_objects",
    "semantic_ticker_day_row_sum","semantic_bundle_count","first_observed_date","first_observed_time",
    "last_observed_date","last_observed_time","status","next_stage","data_plane_impl_version"
)

def _sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def _load(path: Path): return json.loads(path.read_text(encoding="utf-8"))

def _stable_sources(root: Path):
    g=_load(root/"00_MANIFESTS/GLOBAL_DATA_PLANE_MANIFEST.json")
    out={}
    for src in g.get("sources",[]):
        out[src["source_drive_id"]]={k:src.get(k) for k in STABLE_SOURCE_KEYS}
    return out

def _file_hashes(root: Path, folder: str, suffixes: tuple[str,...]):
    base=root/folder
    if not base.exists(): return {}
    return {str(p.relative_to(base)):_sha256(p) for p in sorted(base.rglob("*")) if p.is_file() and p.suffix in suffixes}

def compare_runtime_roots(baseline: str|Path, candidate: str|Path):
    b=Path(baseline); c=Path(candidate)
    checks={}
    bs,cs=_stable_sources(b),_stable_sources(c)
    checks["stable_source_manifest"]={"pass":bs==cs,"baseline_sources":len(bs),"candidate_sources":len(cs)}
    for name,folder,sfx in [
        ("physical_shards","01_ACCESS_SHARDS",(".bin",)),
        ("semantic_bundles","02_SEMANTIC_BUNDLES",(".jsonl",)),
    ]:
        bh=_file_hashes(b,folder,sfx); ch=_file_hashes(c,folder,sfx)
        checks[name]={"pass":bh==ch,"baseline_files":len(bh),"candidate_files":len(ch)}
    def normalize(obj):
        if isinstance(obj,dict): return {k:normalize(v) for k,v in obj.items() if k not in {"created_at_utc","accepted_at_utc","refresh_id","started_at_utc","finished_at_utc"}}
        if isinstance(obj,list): return [normalize(v) for v in obj]
        if isinstance(obj,str) and ("/UNIVERSAL_BEHAVIOR_DATA_PLANE_" in obj or "\\UNIVERSAL_BEHAVIOR_DATA_PLANE_" in obj):
            return obj.replace(str(b),"<RUN_ROOT>").replace(str(c),"<RUN_ROOT>")
        return obj
    def json_map(root,folder):
        base=root/folder; out={}
        if not base.exists(): return out
        for p in sorted(base.rglob("*.json")):
            out[str(p.relative_to(base))]=normalize(_load(p))
        return out
    bm=json_map(b,"03_MARKET_DAY_INDEX"); cm=json_map(c,"03_MARKET_DAY_INDEX")
    checks["market_day_index"]={"pass":bm==cm,"baseline_files":len(bm),"candidate_files":len(cm)}
    return {"pass":all(x["pass"] for x in checks.values()),"checks":checks}
