from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "A1_V23_SHARD_MOTIF_REGISTRY_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"


def canon(obj: Mapping[str, Any]) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def identity(obj: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(obj.get("source") or ""), str(obj.get("ticker") or ""), str(obj.get("date") or "")


def clock_minute(timestamp: str) -> str:
    m = re.search(r"\b(\d{2}:\d{2})\b", timestamp)
    return m.group(1) if m else "UNKNOWN"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(shard: Mapping[str, Any], artifact_digest: str) -> str:
    payload = {
        "schema": SCHEMA,
        "artifact_digest": artifact_digest,
        "shard_id": shard["shard_id"],
        "source": shard["source"],
        "ticker_days": int(shard["ticker_days"]),
        "minute_rows": int(shard["minute_rows"]),
        "zero_session_ticker_days": int(shard["zero_session_ticker_days"]),
        "episode_runs": int(shard["episode_runs"]),
        "episode_rows": int(shard["episode_rows"]),
        "identity_digest_sha256": shard["identity_digest_sha256"],
        "ticker_day_digest_sha256": shard["ticker_day_digest_sha256"],
        "episode_run_digest_sha256": shard["episode_run_digest_sha256"],
    }
    return hashlib.sha256(canon(payload)).hexdigest()


def motif_key(parts: tuple[str, ...]) -> str:
    return json.dumps(parts, separators=(",", ":"), ensure_ascii=False)


def update_bounds(bounds: dict[str, list[str | None]], key: str, ts: str) -> None:
    if not ts:
        return
    cur = bounds.setdefault(key, [None, None])
    if cur[0] is None or ts < cur[0]:
        cur[0] = ts
    if cur[1] is None or ts > cur[1]:
        cur[1] = ts


def process_one(*, shard_root: Path, out_root: Path, shard: Mapping[str, Any], artifact_digest: str) -> dict[str, Any]:
    sid = str(shard["shard_id"])
    source_expected = str(shard["source"])
    fp = fingerprint(shard, artifact_digest)
    out_dir = out_root / "registries"
    cp_dir = out_root / "checkpoints"
    out_dir.mkdir(parents=True, exist_ok=True)
    cp_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sid}.json.gz"
    cp_path = cp_dir / f"{sid}.json"

    if cp_path.is_file() and out_path.is_file():
        try:
            old = json.loads(cp_path.read_text(encoding="utf-8"))
            if old.get("status") == "PASS" and old.get("fingerprint") == fp and old.get("output_sha256") == sha256_file(out_path):
                old = dict(old)
                old["reused_existing_pass"] = True
                return old
        except Exception:
            pass

    td_path = shard_root / "ticker_days" / f"{sid}.jsonl.gz"
    ep_path = shard_root / "episode_runs" / f"{sid}.jsonl.gz"
    if not td_path.is_file() or not ep_path.is_file():
        raise RuntimeError(f"V23_INPUT_MISSING:{sid}")

    td_rows: dict[tuple[str, str, str], tuple[int, str]] = {}
    zero = 0
    with gzip.open(td_path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            key = identity(rec)
            if not all(key) or key in td_rows:
                raise RuntimeError(f"V23_BAD_TD_IDENTITY:{sid}:{line_no}:{key}")
            if key[0] != source_expected:
                raise RuntimeError(f"V23_SOURCE_BOUNDARY:{sid}:{key[0]}:{source_expected}")
            rows = int(rec.get("rows", 0))
            td_rows[key] = (rows, str(rec.get("block") or ""))
            zero += int(rows == 0 or bool(rec.get("zero_session_eligible", False)))

    if len(td_rows) != int(shard["ticker_days"]) or zero != int(shard["zero_session_ticker_days"]):
        raise RuntimeError(f"V23_TD_ACCOUNTING:{sid}")

    state = Counter()
    transition = Counter()
    branch3 = Counter()
    state_unique = Counter()
    transition_unique = Counter()
    branch3_unique = Counter()
    clock = Counter()
    period = Counter()
    bounds: dict[str, list[str | None]] = {}
    seen_nonzero: set[tuple[str, str, str]] = set()

    total_runs = 0
    total_rows = 0
    total_transitions = 0
    total_branches = 0
    current_key: tuple[str, str, str] | None = None
    group: list[dict[str, Any]] = []

    def finalize(key: tuple[str, str, str] | None, runs: list[dict[str, Any]]) -> None:
        nonlocal total_transitions, total_branches
        if key is None:
            return
        if key not in td_rows:
            raise RuntimeError(f"V23_EPISODE_ORPHAN:{sid}:{key}")
        expected_rows, td_block = td_rows[key]
        row_sum = sum(int(r.get("row_count", 0)) for r in runs)
        if row_sum != expected_rows:
            raise RuntimeError(f"V23_EPISODE_ROWS:{sid}:{key}:{row_sum}:{expected_rows}")
        if expected_rows == 0:
            if runs:
                raise RuntimeError(f"V23_ZERO_WITH_RUNS:{sid}:{key}")
            return
        if not runs:
            raise RuntimeError(f"V23_NONZERO_WITHOUT_RUNS:{sid}:{key}")
        seen_nonzero.add(key)
        seen_s: set[str] = set()
        seen_t: set[str] = set()
        seen_b: set[str] = set()
        for i, run in enumerate(runs):
            token = str(run.get("token") or "")
            if not token:
                raise RuntimeError(f"V23_EMPTY_TOKEN:{sid}:{key}:{i}")
            block = str(run.get("block") or td_block)
            source = str(run.get("source") or key[0])
            ts = str(run.get("start_timestamp") or "")

            sk = motif_key((token,))
            state[sk] += 1
            state_unique[sk] += int(sk not in seen_s)
            seen_s.add(sk)
            clock[("STATE", sk, clock_minute(ts))] += 1
            period[("STATE", sk, block, source)] += 1
            update_bounds(bounds, "STATE:" + sk, ts)

            if i >= 1:
                prev = str(runs[i - 1].get("token") or "")
                tk = motif_key((prev, token))
                transition[tk] += 1
                transition_unique[tk] += int(tk not in seen_t)
                seen_t.add(tk)
                clock[("TRANSITION", tk, clock_minute(ts))] += 1
                period[("TRANSITION", tk, block, source)] += 1
                update_bounds(bounds, "TRANSITION:" + tk, ts)
                total_transitions += 1

            if i >= 2:
                prev2 = str(runs[i - 2].get("token") or "")
                prev1 = str(runs[i - 1].get("token") or "")
                bk = motif_key((prev2, prev1, token))
                branch3[bk] += 1
                branch3_unique[bk] += int(bk not in seen_b)
                seen_b.add(bk)
                clock[("BRANCH3", bk, clock_minute(ts))] += 1
                period[("BRANCH3", bk, block, source)] += 1
                update_bounds(bounds, "BRANCH3:" + bk, ts)
                total_branches += 1

    with gzip.open(ep_path, "rt", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            key = identity(rec)
            if not all(key) or key[0] != source_expected:
                raise RuntimeError(f"V23_BAD_EP_IDENTITY:{sid}:{line_no}:{key}")
            if current_key is None:
                current_key = key
            elif key != current_key:
                finalize(current_key, group)
                current_key = key
                group = []
            group.append(rec)
            total_runs += 1
            total_rows += int(rec.get("row_count", 0))
    finalize(current_key, group)

    expected_nonzero = {k for k, (rows, _) in td_rows.items() if rows > 0}
    if seen_nonzero != expected_nonzero:
        raise RuntimeError(f"V23_NONZERO_COVERAGE:{sid}:{len(expected_nonzero-seen_nonzero)}:{len(seen_nonzero-expected_nonzero)}")
    if total_runs != int(shard["episode_runs"]) or total_rows != int(shard["episode_rows"]):
        raise RuntimeError(f"V23_EP_ACCOUNTING:{sid}:{total_runs}:{total_rows}")

    registry = {
        "schema": SCHEMA,
        "status": "PASS",
        "research_status": STATUS,
        "shard_id": sid,
        "source": source_expected,
        "fingerprint": fp,
        "contract": {
            "motif_definition_uses_future_outcome": False,
            "state_is_exact_v22_token": True,
            "transition_is_exact_adjacent_state_change": True,
            "branch3_is_exact_two_state_prefix_plus_observed_next_state": True,
            "timing_uses_actual_run_start_timestamp": True,
            "no_signal_thresholds_added": True,
        },
        "accounting": {
            "ticker_days": len(td_rows),
            "minute_rows": sum(v[0] for v in td_rows.values()),
            "zero_session_ticker_days": zero,
            "episode_runs": total_runs,
            "episode_rows": total_rows,
            "transition_occurrences": total_transitions,
            "branch3_occurrences": total_branches,
        },
        "state": {k: {"occurrences": int(v), "unique_ticker_days": int(state_unique[k]), "first_start_timestamp": bounds.get("STATE:" + k, [None, None])[0], "last_start_timestamp": bounds.get("STATE:" + k, [None, None])[1]} for k, v in state.items()},
        "transition": {k: {"occurrences": int(v), "unique_ticker_days": int(transition_unique[k]), "first_start_timestamp": bounds.get("TRANSITION:" + k, [None, None])[0], "last_start_timestamp": bounds.get("TRANSITION:" + k, [None, None])[1]} for k, v in transition.items()},
        "branch3": {k: {"occurrences": int(v), "unique_ticker_days": int(branch3_unique[k]), "first_start_timestamp": bounds.get("BRANCH3:" + k, [None, None])[0], "last_start_timestamp": bounds.get("BRANCH3:" + k, [None, None])[1]} for k, v in branch3.items()},
        "clock_counts": [[kind, key, minute, int(v)] for (kind, key, minute), v in clock.items()],
        "period_counts": [[kind, key, block, source, int(v)] for (kind, key, block, source), v in period.items()],
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="\n") as fh:
        json.dump(registry, fh, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    tmp.replace(out_path)
    out_sha = sha256_file(out_path)
    cp = {
        "schema": SCHEMA,
        "status": "PASS",
        "shard_id": sid,
        "source": source_expected,
        "fingerprint": fp,
        "output": str(out_path),
        "output_sha256": out_sha,
        **registry["accounting"],
        "unique_state_motifs": len(state),
        "unique_transition_motifs": len(transition),
        "unique_branch3_motifs": len(branch3),
        "reused_existing_pass": False,
    }
    cp_path.write_text(json.dumps(cp, indent=2, sort_keys=True), encoding="utf-8")
    return cp


def run(*, shard_root: Path, out_root: Path, artifact_digest: str) -> dict[str, Any]:
    manifest_path = shard_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("V23_SHARD_MANIFEST_MISSING")
    src = json.loads(manifest_path.read_text(encoding="utf-8"))
    if src.get("status") != "PASS" or src.get("artifact_digest") != artifact_digest:
        raise RuntimeError("V23_SHARD_MANIFEST_NOT_AUTHORIZED")

    checkpoints = [process_one(shard_root=shard_root, out_root=out_root, shard=s, artifact_digest=artifact_digest) for s in src["shards"]]
    totals = {
        "shards": len(checkpoints),
        "ticker_days": sum(int(x["ticker_days"]) for x in checkpoints),
        "minute_rows": sum(int(x["minute_rows"]) for x in checkpoints),
        "zero_session_ticker_days": sum(int(x["zero_session_ticker_days"]) for x in checkpoints),
        "episode_runs": sum(int(x["episode_runs"]) for x in checkpoints),
        "episode_rows": sum(int(x["episode_rows"]) for x in checkpoints),
        "transition_occurrences": sum(int(x["transition_occurrences"]) for x in checkpoints),
        "branch3_occurrences": sum(int(x["branch3_occurrences"]) for x in checkpoints),
        "reused_shards": sum(int(bool(x.get("reused_existing_pass"))) for x in checkpoints),
    }
    r = src["reconciliation"]
    ok = (
        totals["shards"] == int(src["shard_count"])
        and totals["ticker_days"] == int(r["ticker_days"])
        and totals["minute_rows"] == int(r["minute_rows_from_ticker_days"])
        and totals["zero_session_ticker_days"] == int(r["zero_session_ticker_days"])
        and totals["episode_runs"] == int(r["episode_runs"])
        and totals["episode_rows"] == int(r["minute_rows_partitioned_by_episode_runs"])
    )
    result = {
        "schema": SCHEMA,
        "status": "PASS" if ok else "FAIL",
        "research_status": STATUS,
        "artifact_digest": artifact_digest,
        "input_shard_manifest_sha256": sha256_file(manifest_path),
        "reconciliation": {**totals, "pass": ok},
        "contract": {
            "reads_only_v22_reconciled_shards": True,
            "raw_reread": False,
            "census_rerun": False,
            "full_v22_artifact_reread": False,
            "checkpoint_per_shard": True,
            "reuse_passed_shard_without_reread": True,
            "reserved_oos_untouched": True,
        },
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not ok:
        raise RuntimeError("V23_GLOBAL_RECONCILIATION_FAILED")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--shard-root", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--artifact-digest", required=True)
    a = p.parse_args()
    report = run(shard_root=Path(a.shard_root), out_root=Path(a.output_root), artifact_digest=a.artifact_digest)
    print(json.dumps({"schema": report["schema"], "status": report["status"], "reconciliation": report["reconciliation"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
