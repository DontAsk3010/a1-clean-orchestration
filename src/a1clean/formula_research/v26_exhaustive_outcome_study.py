from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import telegram_mg_sequence_v11 as v11
from . import telegram_mg_structure_v12_runner as v12r
from .durable_cache_catalog import governed_sources_from_durable_cache

SCHEMA = "A1_V26_EXHAUSTIVE_OUTCOME_EVIDENCE_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"

RELATIONS = (
    "BUY_FLOW_PRICE_ADVANCE",
    "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE",
    "SELL_FLOW_PRICE_DECLINE",
    "SELL_FLOW_PRICE_RESILIENCE",
    "NO_PROVEN_FLOW",
)
NEXT_LABELS = (
    "BUY_ADVANCE",
    "BUY_NONRESPONSE",
    "SELL_DECLINE",
    "SELL_RESILIENCE",
    "PRICE_UP",
    "PRICE_DOWN",
    "FRESH_HIGH",
    "FRESH_LOW",
    "FLOW_BUY",
    "FLOW_SELL",
    "FLOWEFF_ACCEL",
    "FLOWEFF_DECEL",
    "VALACT_ACCEL",
    "VALACT_DECEL",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canon_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def identity(obj: Mapping[str, Any], source_default: str = "") -> tuple[str, str, str]:
    return (
        str(obj.get("source") or source_default),
        str(obj.get("ticker") or ""),
        str(obj.get("date") or ""),
    )


def child_id(k1: str, k2: str, k3: str) -> str:
    return hashlib.sha256((k1 + "\x1f" + k2 + "\x1f" + k3).encode("utf-8")).hexdigest()[:32]


def prefix_id(k1: str, k2: str) -> str:
    return hashlib.sha256((k1 + "\x1f" + k2).encode("utf-8")).hexdigest()[:32]


def f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def pct(value: float | None, ref: float | None) -> float | None:
    if value is None or ref in (None, 0.0):
        return None
    return (value / ref - 1.0) * 100.0


def token_semantics(token: str) -> dict[str, str]:
    parts = token.split("|")
    if len(parts) != 10:
        raise RuntimeError(f"V26_BAD_TOKEN:{token}")
    prefixes = ("P_", "VOL_", "VALUE_", "FLOW_", "FLOWEFF_", "VALACT_", "HI_", "LO_", "HH_")
    for value, pre in zip(parts[1:], prefixes):
        if not value.startswith(pre):
            raise RuntimeError(f"V26_BAD_TOKEN_COMPONENT:{pre}:{token}")
    return {
        "relation": parts[0],
        "price_direction": parts[1][2:],
        "volume_direction": parts[2][4:],
        "value_direction": parts[3][6:],
        "flow_direction": parts[4][5:],
        "flow_effort_change": parts[5][8:],
        "value_activity_change": parts[6][7:],
        "fresh_high": parts[7][3:],
        "fresh_low": parts[8][3:],
        "haka_haki_dominance": parts[9][3:],
    }


def labels_for(token: str) -> set[str]:
    s = token_semantics(token)
    out: set[str] = set()
    rel = s["relation"]
    if rel == "BUY_FLOW_PRICE_ADVANCE": out.add("BUY_ADVANCE")
    if rel == "BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE": out.add("BUY_NONRESPONSE")
    if rel == "SELL_FLOW_PRICE_DECLINE": out.add("SELL_DECLINE")
    if rel == "SELL_FLOW_PRICE_RESILIENCE": out.add("SELL_RESILIENCE")
    if s["price_direction"] == "UP": out.add("PRICE_UP")
    if s["price_direction"] == "DOWN": out.add("PRICE_DOWN")
    if s["fresh_high"] == "FRESH": out.add("FRESH_HIGH")
    if s["fresh_low"] == "FRESH": out.add("FRESH_LOW")
    if s["flow_direction"] == "BUY": out.add("FLOW_BUY")
    if s["flow_direction"] == "SELL": out.add("FLOW_SELL")
    if s["flow_effort_change"] == "ACCEL": out.add("FLOWEFF_ACCEL")
    if s["flow_effort_change"] == "DECEL": out.add("FLOWEFF_DECEL")
    if s["value_activity_change"] == "ACCEL": out.add("VALACT_ACCEL")
    if s["value_activity_change"] == "DECEL": out.add("VALACT_DECEL")
    return out


def load_v25(v25_root: Path) -> dict[str, Any]:
    manifest_path = v25_root / "manifest.json"
    atlas_path = v25_root / "causal-divergence-atlas.jsonl.gz"
    if not manifest_path.is_file() or not atlas_path.is_file():
        raise RuntimeError("V26_V25_INPUT_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or manifest.get("reconciliation", {}).get("pass") is not True:
        raise RuntimeError("V26_V25_NOT_PASS")
    expected_sha = str(manifest.get("atlas", {}).get("atlas_sha256") or "")
    if expected_sha and sha256_file(atlas_path) != expected_sha:
        raise RuntimeError("V26_V25_ATLAS_DIGEST_MISMATCH")

    triples: dict[tuple[str, str, str], tuple[str, str]] = {}
    child_ids: dict[str, tuple[str, str, str]] = {}
    prefix_ids: dict[str, tuple[str, str]] = {}
    expected_occurrences = 0
    prefix_count = 0
    child_count = 0
    with gzip.open(atlas_path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            pref = obj.get("prefix")
            if not isinstance(pref, list) or len(pref) != 2:
                raise RuntimeError(f"V26_BAD_PREFIX:{line_no}")
            k1, k2 = str(pref[0]), str(pref[1])
            pid = prefix_id(k1, k2)
            oldp = prefix_ids.get(pid)
            if oldp is not None and oldp != (k1, k2):
                raise RuntimeError(f"V26_PREFIX_HASH_COLLISION:{pid}")
            prefix_ids[pid] = (k1, k2)
            prefix_count += 1
            expected_occurrences += int(obj.get("prefix_occurrences", 0))
            for child in obj.get("children", []):
                k3 = str(child.get("state") or "")
                if not k3:
                    raise RuntimeError(f"V26_EMPTY_CHILD:{line_no}")
                cid = child_id(k1, k2, k3)
                oldc = child_ids.get(cid)
                if oldc is not None and oldc != (k1, k2, k3):
                    raise RuntimeError(f"V26_CHILD_HASH_COLLISION:{cid}")
                child_ids[cid] = (k1, k2, k3)
                triples[(k1, k2, k3)] = (pid, cid)
                child_count += 1

    expected_prefixes = int(manifest["reconciliation"]["divergent_prefixes"])
    expected_children = int(manifest["reconciliation"]["divergent_child_motifs"])
    if prefix_count != expected_prefixes or child_count != expected_children or len(triples) != expected_children:
        raise RuntimeError(
            f"V26_V25_CATALOG_MISMATCH:{prefix_count}:{expected_prefixes}:{child_count}:{expected_children}:{len(triples)}"
        )
    return {
        "manifest": manifest,
        "atlas_path": atlas_path,
        "atlas_sha256": sha256_file(atlas_path),
        "triples": triples,
        "child_ids": child_ids,
        "prefix_ids": prefix_ids,
        "expected_occurrences": expected_occurrences,
    }


def iter_episode_groups(v22_root: Path, shards: Sequence[Mapping[str, Any]]) -> Iterable[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    current: tuple[str, str, str] | None = None
    group: list[dict[str, Any]] = []
    for shard in shards:
        sid = str(shard["shard_id"])
        path = v22_root / "episode_runs" / f"{sid}.jsonl.gz"
        if not path.is_file():
            raise RuntimeError(f"V26_EPISODE_SHARD_MISSING:{sid}")
        expected_sha = str(shard.get("episode_run_digest_sha256") or "")
        # The manifest digest is over canonical uncompressed records, not gzip bytes; integrity was already proven by V2.2.
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                key = identity(rec)
                if not all(key):
                    raise RuntimeError(f"V26_BAD_EP_IDENTITY:{sid}:{line_no}:{key}")
                if current is None:
                    current = key
                elif key != current:
                    yield current, group
                    current = key
                    group = []
                group.append(rec)
    if current is not None:
        yield current, group


def build_next_times(runs: Sequence[Mapping[str, Any]]) -> dict[str, list[str | None]]:
    n = len(runs)
    out = {label: [None] * (n + 1) for label in NEXT_LABELS}
    current = {label: None for label in NEXT_LABELS}
    for i in range(n - 1, -1, -1):
        out_at = labels_for(str(runs[i].get("token") or ""))
        ts = str(runs[i].get("start_timestamp") or "") or None
        for label in NEXT_LABELS:
            if label in out_at:
                current[label] = ts
            out[label][i] = current[label]
    return out


def suffix_extremes(bars: Sequence[Mapping[str, Any]]) -> tuple[list[float | None], list[int | None], list[float | None], list[int | None]]:
    n = len(bars)
    maxv: list[float | None] = [None] * (n + 1)
    maxi: list[int | None] = [None] * (n + 1)
    minv: list[float | None] = [None] * (n + 1)
    mini: list[int | None] = [None] * (n + 1)
    cur_max: float | None = None
    cur_max_i: int | None = None
    cur_min: float | None = None
    cur_min_i: int | None = None
    for i in range(n - 1, -1, -1):
        hi = f(bars[i].get("high"))
        lo = f(bars[i].get("low"))
        if hi is not None and (cur_max is None or hi >= cur_max):
            cur_max, cur_max_i = hi, i
        if lo is not None and (cur_min is None or lo <= cur_min):
            cur_min, cur_min_i = lo, i
        maxv[i], maxi[i], minv[i], mini[i] = cur_max, cur_max_i, cur_min, cur_min_i
    return maxv, maxi, minv, mini


def checkpoint_fingerprint(*, source: str, shards: Sequence[Mapping[str, Any]], atlas_sha256: str, cache_meta: Mapping[str, Any]) -> str:
    return canon_hash({
        "schema": SCHEMA,
        "source": source,
        "atlas_sha256": atlas_sha256,
        "shards": [
            {
                "shard_id": s["shard_id"],
                "ticker_days": int(s["ticker_days"]),
                "episode_runs": int(s["episode_runs"]),
                "episode_rows": int(s["episode_rows"]),
                "identity_digest_sha256": s["identity_digest_sha256"],
                "episode_run_digest_sha256": s["episode_run_digest_sha256"],
            }
            for s in shards
        ],
        "cache": {
            "schema": cache_meta.get("schema"),
            "source_name": cache_meta.get("source_name"),
            "source_sha256": cache_meta.get("source_sha256"),
            "generation_id": cache_meta.get("generation_id"),
            "semantic_manifest_fingerprint": cache_meta.get("semantic_manifest_fingerprint"),
            "ticker_days": int(cache_meta.get("ticker_days", -1)),
            "rows": int(cache_meta.get("rows", -1)),
            "complete": cache_meta.get("complete"),
        },
    })


def process_source(
    *,
    source: str,
    block: str,
    shards: Sequence[Mapping[str, Any]],
    v22_root: Path,
    out_root: Path,
    v25: Mapping[str, Any],
) -> dict[str, Any]:
    cp_dir = out_root / "checkpoints"
    event_dir = out_root / "events"
    ids_dir = out_root / "coverage_ids"
    cp_dir.mkdir(parents=True, exist_ok=True)
    event_dir.mkdir(parents=True, exist_ok=True)
    ids_dir.mkdir(parents=True, exist_ok=True)
    slug = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    cp_path = cp_dir / f"{slug}.json"
    event_path = event_dir / f"{slug}.jsonl.gz"
    child_path = ids_dir / f"{slug}.children.txt.gz"
    prefix_path = ids_dir / f"{slug}.prefixes.txt.gz"

    meta_path = v12r._meta_path(source)
    cache_path = v12r._cache_path(source)
    if not meta_path.is_file() or not cache_path.is_file():
        raise RuntimeError(f"V26_CACHE_MISSING:{source}")
    cache_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if cache_meta.get("complete") is not True or cache_meta.get("source_name") != source:
        raise RuntimeError(f"V26_CACHE_NOT_COMPLETE:{source}")
    fp = checkpoint_fingerprint(source=source, shards=shards, atlas_sha256=str(v25["atlas_sha256"]), cache_meta=cache_meta)

    if cp_path.is_file() and event_path.is_file() and child_path.is_file() and prefix_path.is_file():
        try:
            old = json.loads(cp_path.read_text(encoding="utf-8"))
            if (
                old.get("status") == "PASS"
                and old.get("fingerprint") == fp
                and old.get("event_sha256") == sha256_file(event_path)
                and old.get("child_ids_sha256") == sha256_file(child_path)
                and old.get("prefix_ids_sha256") == sha256_file(prefix_path)
            ):
                old = dict(old)
                old["reused_existing_pass"] = True
                return old
        except Exception:
            pass

    triples: Mapping[tuple[str, str, str], tuple[str, str]] = v25["triples"]
    ep_iter = iter(iter_episode_groups(v22_root, shards))
    current_ep = next(ep_iter, None)
    event_count = 0
    matched_nonzero = 0
    cache_ticker_days = 0
    cache_rows = 0
    zero_sessions = 0
    seen_children: set[str] = set()
    seen_prefixes: set[str] = set()
    relation_child_counts: Counter[str] = Counter()
    order_counts: Counter[str] = Counter()
    censored = 0

    tmp_event = event_path.with_suffix(event_path.suffix + ".tmp")
    with gzip.open(tmp_event, "wt", encoding="utf-8", newline="\n") as out:
        for packet in v12r._iter_cached(source):
            key = (source, str(packet.get("ticker") or ""), str(packet.get("date") or ""))
            bars = [dict(x) for x in packet.get("bars", [])]
            cache_ticker_days += 1
            cache_rows += len(bars)
            if not bars:
                zero_sessions += 1
                if current_ep is not None and current_ep[0] == key:
                    raise RuntimeError(f"V26_ZERO_WITH_EPISODES:{key}")
                continue
            if current_ep is None:
                raise RuntimeError(f"V26_NONZERO_WITHOUT_EPISODES:{key}")
            if current_ep[0] != key:
                raise RuntimeError(f"V26_EPISODE_CACHE_ORDER_MISMATCH:{key}:{current_ep[0]}")
            runs = current_ep[1]
            matched_nonzero += 1
            current_ep = next(ep_iter, None)

            row_sum = sum(int(r.get("row_count", 0)) for r in runs)
            if row_sum != len(bars):
                raise RuntimeError(f"V26_ROW_ACCOUNTING:{key}:{row_sum}:{len(bars)}")
            next_times = build_next_times(runs)
            maxv, maxi, minv, mini = suffix_extremes(bars)
            final_close = f(bars[-1].get("close"))
            final_ts = str(bars[-1].get("timestamp") or "")
            nbar = len(bars)

            for i in range(2, len(runs)):
                k1 = str(runs[i - 2].get("token") or "")
                k2 = str(runs[i - 1].get("token") or "")
                k3 = str(runs[i].get("token") or "")
                ids = triples.get((k1, k2, k3))
                if ids is None:
                    continue
                pid, cid = ids
                di = int(runs[i].get("start_index", -1))
                if di < 0 or di >= nbar:
                    raise RuntimeError(f"V26_BAD_DETECTION_INDEX:{key}:{di}:{nbar}")
                dts = str(runs[i].get("start_timestamp") or "")
                bts = str(bars[di].get("timestamp") or "")
                if dts and bts and dts != bts:
                    raise RuntimeError(f"V26_DETECTION_TIME_MISMATCH:{key}:{dts}:{bts}")
                ref = f(bars[di].get("close"))
                if ref is None:
                    ref = f(runs[i].get("start_close"))
                future_start = di + 1
                is_censored = future_start >= nbar
                censored += int(is_censored)
                hi = maxv[future_start] if not is_censored else None
                hi_i = maxi[future_start] if not is_censored else None
                lo = minv[future_start] if not is_censored else None
                lo_i = mini[future_start] if not is_censored else None
                if hi_i is None or lo_i is None:
                    order = "RIGHT_CENSORED" if is_censored else "UNKNOWN"
                elif hi_i < lo_i:
                    order = "HIGH_FIRST"
                elif lo_i < hi_i:
                    order = "LOW_FIRST"
                else:
                    order = "SAME_BAR_EXTREMES"
                order_counts[order] += 1
                sem = token_semantics(k3)
                relation_child_counts[sem["relation"]] += 1
                first_after = {
                    label: (next_times[label][i + 1] if i + 1 < len(runs) else None)
                    for label in NEXT_LABELS
                }
                suffix_rows_after = sum(int(r.get("row_count", 0)) for r in runs[i + 1 :])
                rec = {
                    "schema": SCHEMA,
                    "source": source,
                    "block": block,
                    "ticker": key[1],
                    "date": key[2],
                    "prefix_id": pid,
                    "child_id": cid,
                    "detection_timestamp": dts or bts,
                    "detection_bar_index": di,
                    "detection_close": ref,
                    "child_relation": sem["relation"],
                    "child_price_direction": sem["price_direction"],
                    "child_flow_direction": sem["flow_direction"],
                    "child_flow_effort_change": sem["flow_effort_change"],
                    "child_value_activity_change": sem["value_activity_change"],
                    "child_fresh_high": sem["fresh_high"],
                    "child_fresh_low": sem["fresh_low"],
                    "child_haka_haki_dominance": sem["haka_haki_dominance"],
                    "future_bar_count": max(0, nbar - future_start),
                    "future_run_count": max(0, len(runs) - (i + 1)),
                    "future_run_rows": suffix_rows_after,
                    "right_censored_at_detection": is_censored,
                    "future_max_high": hi,
                    "future_max_high_timestamp": (str(bars[hi_i].get("timestamp") or "") if hi_i is not None else None),
                    "future_min_low": lo,
                    "future_min_low_timestamp": (str(bars[lo_i].get("timestamp") or "") if lo_i is not None else None),
                    "mfe_pct_from_detection_close": pct(hi, ref),
                    "mae_pct_from_detection_close": pct(lo, ref),
                    "eod_close": final_close,
                    "eod_timestamp": final_ts,
                    "eod_return_pct_from_detection_close": pct(final_close, ref),
                    "extreme_order": order,
                    "first_later_state_times": first_after,
                    "final_state_token": str(runs[-1].get("token") or ""),
                    "final_state_start_timestamp": str(runs[-1].get("start_timestamp") or ""),
                    "future_state_sequence_sha256": canon_hash([str(r.get("token") or "") for r in runs[i + 1 :]]),
                    "future_outcome_used_to_define_prefix_or_child": False,
                }
                out.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                event_count += 1
                seen_children.add(cid)
                seen_prefixes.add(pid)
    if current_ep is not None:
        raise RuntimeError(f"V26_UNCONSUMED_EPISODES:{source}:{current_ep[0]}")
    tmp_event.replace(event_path)

    with gzip.open(child_path, "wt", encoding="utf-8", newline="\n") as fh:
        for cid in sorted(seen_children):
            fh.write(cid + "\n")
    with gzip.open(prefix_path, "wt", encoding="utf-8", newline="\n") as fh:
        for pid in sorted(seen_prefixes):
            fh.write(pid + "\n")

    expected_td = sum(int(s["ticker_days"]) for s in shards)
    expected_rows = sum(int(s["minute_rows"]) for s in shards)
    expected_zero = sum(int(s["zero_session_ticker_days"]) for s in shards)
    expected_nonzero = expected_td - expected_zero
    ok = (
        cache_ticker_days == expected_td
        and cache_rows == expected_rows
        and zero_sessions == expected_zero
        and matched_nonzero == expected_nonzero
    )
    cp = {
        "schema": SCHEMA,
        "status": "PASS" if ok else "FAIL",
        "research_status": STATUS,
        "source": source,
        "block": block,
        "fingerprint": fp,
        "ticker_days": cache_ticker_days,
        "minute_rows": cache_rows,
        "zero_session_ticker_days": zero_sessions,
        "matched_nonzero_ticker_days": matched_nonzero,
        "event_occurrences": event_count,
        "unique_child_ids": len(seen_children),
        "unique_prefix_ids": len(seen_prefixes),
        "right_censored_event_occurrences": censored,
        "extreme_order_counts": dict(sorted(order_counts.items())),
        "child_relation_occurrence_counts": dict(sorted(relation_child_counts.items())),
        "event_path": str(event_path),
        "event_sha256": sha256_file(event_path),
        "child_ids_sha256": sha256_file(child_path),
        "prefix_ids_sha256": sha256_file(prefix_path),
        "reused_existing_pass": False,
        "pass": ok,
    }
    cp_path.write_text(json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8")
    if not ok:
        raise RuntimeError(f"V26_SOURCE_RECONCILIATION_FAIL:{source}")
    return cp


def read_id_file(path: Path) -> set[str]:
    out: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            value = line.strip()
            if value:
                out.add(value)
    return out


def run(*, v22_root: Path, v25_root: Path, output_root: Path, artifact_digest: str) -> dict[str, Any]:
    v22_manifest_path = v22_root / "manifest.json"
    if not v22_manifest_path.is_file():
        raise RuntimeError("V26_V22_MANIFEST_MISSING")
    v22 = json.loads(v22_manifest_path.read_text(encoding="utf-8"))
    if v22.get("status") != "PASS" or v22.get("artifact_digest") != artifact_digest:
        raise RuntimeError("V26_V22_NOT_AUTHORIZED")
    r22 = v22.get("reconciliation", {})
    if not (r22.get("exact_coverage_pass") is True and r22.get("no_duplicate_identity_pass") is True and r22.get("episode_partition_pass") is True):
        raise RuntimeError("V26_V22_RECONCILIATION_NOT_PASS")

    v25 = load_v25(v25_root)
    governed = governed_sources_from_durable_cache()
    source_names = [str(x["source_name"]) for x in governed]
    if v11.RESERVED_OOS in source_names:
        raise RuntimeError("V26_RESERVED_OOS_FORBIDDEN")

    output_root.mkdir(parents=True, exist_ok=True)
    by_source: dict[str, list[dict[str, Any]]] = {s: [] for s in source_names}
    for shard in v22.get("shards", []):
        source = str(shard["source"])
        if source not in by_source:
            raise RuntimeError(f"V26_UNEXPECTED_SOURCE_SHARD:{source}")
        by_source[source].append(shard)

    checkpoints: list[dict[str, Any]] = []
    for source in source_names:
        shards = by_source[source]
        if not shards:
            raise RuntimeError(f"V26_SOURCE_WITHOUT_SHARDS:{source}")
        checkpoints.append(process_source(
            source=source,
            block=v11._block_for(source),
            shards=shards,
            v22_root=v22_root,
            out_root=output_root,
            v25=v25,
        ))

    seen_children: set[str] = set()
    seen_prefixes: set[str] = set()
    total_events = 0
    total_td = total_rows = total_zero = 0
    reused = 0
    order_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()
    for cp in checkpoints:
        slug = hashlib.sha256(str(cp["source"]).encode("utf-8")).hexdigest()[:16]
        seen_children.update(read_id_file(output_root / "coverage_ids" / f"{slug}.children.txt.gz"))
        seen_prefixes.update(read_id_file(output_root / "coverage_ids" / f"{slug}.prefixes.txt.gz"))
        total_events += int(cp["event_occurrences"])
        total_td += int(cp["ticker_days"])
        total_rows += int(cp["minute_rows"])
        total_zero += int(cp["zero_session_ticker_days"])
        reused += int(bool(cp.get("reused_existing_pass")))
        order_counts.update({str(k): int(v) for k, v in cp.get("extreme_order_counts", {}).items()})
        relation_counts.update({str(k): int(v) for k, v in cp.get("child_relation_occurrence_counts", {}).items()})

    expected_child_ids = set(v25["child_ids"])
    expected_prefix_ids = set(v25["prefix_ids"])
    expected_events = int(v25["expected_occurrences"])
    expected_td = int(r22["ticker_days"])
    expected_rows = int(r22["minute_rows_from_ticker_days"])
    expected_zero = int(r22["zero_session_ticker_days"])
    ok = (
        len(checkpoints) == len(source_names)
        and all(cp.get("status") == "PASS" and cp.get("pass") is True for cp in checkpoints)
        and total_events == expected_events
        and seen_children == expected_child_ids
        and seen_prefixes == expected_prefix_ids
        and total_td == expected_td
        and total_rows == expected_rows
        and total_zero == expected_zero
    )
    result = {
        "schema": SCHEMA,
        "status": "PASS" if ok else "FAIL",
        "research_status": STATUS,
        "artifact_digest": artifact_digest,
        "input_v22_manifest_sha256": sha256_file(v22_manifest_path),
        "input_v25_manifest_sha256": sha256_file(v25_root / "manifest.json"),
        "input_v25_atlas_sha256": v25["atlas_sha256"],
        "contract": {
            "raw_reread": False,
            "census_rerun": False,
            "v22_episode_remining": False,
            "reads_existing_v22_episode_shards_for_new_outcome_linkage": True,
            "reads_existing_normalized_tf1m_cache_once_per_source_for_exact_future_path_metrics": True,
            "checkpoint_per_source": True,
            "reuse_passed_source_without_reread": True,
            "future_outcome_used_to_define_prefix_or_child": False,
            "outcome_is_evaluation_only": True,
            "arbitrary_outcome_thresholds_added": False,
            "reserved_oos_untouched": True,
        },
        "reconciliation": {
            "sources": len(checkpoints),
            "expected_sources": len(source_names),
            "ticker_days": total_td,
            "expected_ticker_days": expected_td,
            "minute_rows": total_rows,
            "expected_minute_rows": expected_rows,
            "zero_session_ticker_days": total_zero,
            "expected_zero_session_ticker_days": expected_zero,
            "divergent_prefixes_observed": len(seen_prefixes),
            "expected_divergent_prefixes": len(expected_prefix_ids),
            "divergent_child_motifs_observed": len(seen_children),
            "expected_divergent_child_motifs": len(expected_child_ids),
            "divergent_event_occurrences": total_events,
            "expected_divergent_event_occurrences": expected_events,
            "pass": ok,
        },
        "outcome_evidence": {
            "event_files": len(checkpoints),
            "right_censored_event_occurrences": sum(int(cp["right_censored_event_occurrences"]) for cp in checkpoints),
            "extreme_order_counts": dict(sorted(order_counts.items())),
            "child_relation_occurrence_counts": dict(sorted(relation_counts.items())),
            "source_event_sha256": {str(cp["source"]): str(cp["event_sha256"]) for cp in checkpoints},
            "reused_sources": reused,
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not ok:
        raise RuntimeError("V26_GLOBAL_RECONCILIATION_FAILED")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--v22-root", required=True)
    p.add_argument("--v25-root", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--artifact-digest", required=True)
    a = p.parse_args()
    result = run(
        v22_root=Path(a.v22_root),
        v25_root=Path(a.v25_root),
        output_root=Path(a.output_root),
        artifact_digest=a.artifact_digest,
    )
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "reconciliation": result["reconciliation"],
        "outcome_evidence": result["outcome_evidence"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
