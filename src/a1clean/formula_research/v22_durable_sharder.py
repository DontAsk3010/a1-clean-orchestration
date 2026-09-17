from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "A1_V22_DURABLE_SHARD_MANIFEST_V1"


def canon(obj: Mapping[str, Any]) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def key_of(obj: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(obj.get("source") or ""), str(obj.get("ticker") or ""), str(obj.get("date") or "")


def slug(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return out[:80] or "source"


def gzwrite(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return gzip.open(path, "wt", encoding="utf-8", newline="\n")


def reusable_manifest(path: Path, artifact_digest: str, ticker_days: int, minute_rows: int) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    r = obj.get("reconciliation", {})
    if (
        obj.get("schema") == SCHEMA
        and obj.get("status") == "PASS"
        and obj.get("artifact_digest") == artifact_digest
        and int(r.get("ticker_days", -1)) == ticker_days
        and int(r.get("minute_rows_from_ticker_days", -1)) == minute_rows
        and r.get("exact_coverage_pass") is True
        and r.get("no_duplicate_identity_pass") is True
        and r.get("episode_partition_pass") is True
    ):
        return obj
    return None


def run(
    *,
    ticker_days_path: Path,
    episode_runs_path: Path,
    output_root: Path,
    artifact_digest: str,
    expected_ticker_days: int,
    expected_minute_rows: int,
    expected_zero_session_ticker_days: int,
    expected_episode_runs: int,
    shard_ticker_days: int,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    old = reusable_manifest(manifest_path, artifact_digest, expected_ticker_days, expected_minute_rows)
    if old is not None:
        old = dict(old)
        old["execution"] = {"reused_existing_pass_manifest": True}
        return old

    for child in list(output_root.iterdir()):
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    for name in ("ticker_days", "episode_runs", "checkpoints"):
        (output_root / name).mkdir(parents=True, exist_ok=True)

    assignments: dict[tuple[str, str, str], str] = {}
    zero_keys: set[tuple[str, str, str]] = set()
    shard_meta: dict[str, dict[str, Any]] = {}
    source_seq: dict[str, int] = {}
    source_accounting: dict[str, dict[str, int]] = {}
    identity_digest = hashlib.sha256()
    td_digest = hashlib.sha256()

    total_td = total_rows = total_zero = 0
    current_source: str | None = None
    current_shard: str | None = None
    current_count = 0
    td_fh = None

    def new_shard(source: str) -> tuple[str, Any]:
        seq = source_seq.get(source, 0) + 1
        source_seq[source] = seq
        sid = f"{slug(source)}__{seq:04d}"
        shard_meta[sid] = {
            "shard_id": sid,
            "source": source,
            "ticker_days": 0,
            "minute_rows": 0,
            "zero_session_ticker_days": 0,
            "episode_runs": 0,
            "episode_rows": 0,
            "first_identity": None,
            "last_identity": None,
            "_td": hashlib.sha256(),
            "_ep": hashlib.sha256(),
            "_id": hashlib.sha256(),
        }
        return sid, gzwrite(output_root / "ticker_days" / f"{sid}.jsonl.gz")

    # Pass 1: read each ticker-day summary exactly once and assign it permanently to one shard.
    with gzip.open(ticker_days_path, "rt", encoding="utf-8") as src:
        for line_no, line in enumerate(src, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            key = key_of(rec)
            if not all(key):
                raise RuntimeError(f"V22_SHARD_INVALID_IDENTITY:{line_no}:{key}")
            if key in assignments:
                raise RuntimeError(f"V22_SHARD_DUPLICATE_IDENTITY:{key}")
            source = key[0]
            if current_shard is None or current_source != source or current_count >= shard_ticker_days:
                if td_fh is not None:
                    td_fh.close()
                current_source = source
                current_shard, td_fh = new_shard(source)
                current_count = 0
            assert td_fh is not None and current_shard is not None

            encoded = canon(rec)
            td_fh.write(encoded.decode("utf-8"))
            rows = int(rec.get("rows", 0))
            is_zero = rows == 0 or bool(rec.get("zero_session_eligible", False))
            if is_zero:
                zero_keys.add(key)
            assignments[key] = current_shard
            key_bytes = ("\x1f".join(key) + "\n").encode("utf-8")
            meta = shard_meta[current_shard]
            meta["ticker_days"] += 1
            meta["minute_rows"] += rows
            meta["zero_session_ticker_days"] += int(is_zero)
            meta["first_identity"] = meta["first_identity"] or list(key)
            meta["last_identity"] = list(key)
            meta["_td"].update(encoded)
            meta["_id"].update(key_bytes)
            identity_digest.update(key_bytes)
            td_digest.update(encoded)

            acc = source_accounting.setdefault(source, {"ticker_days": 0, "minute_rows": 0, "zero_session_ticker_days": 0, "episode_runs": 0, "episode_rows": 0})
            acc["ticker_days"] += 1
            acc["minute_rows"] += rows
            acc["zero_session_ticker_days"] += int(is_zero)
            total_td += 1
            total_rows += rows
            total_zero += int(is_zero)
            current_count += 1
    if td_fh is not None:
        td_fh.close()

    # Pass 2: episode runs are already in ticker-day order. They are partitioned without rereading ticker-day data.
    episode_digest = hashlib.sha256()
    episode_keys: set[tuple[str, str, str]] = set()
    closed_shards: set[str] = set()
    active_shard: str | None = None
    ep_fh = None
    total_episode_runs = total_episode_rows = 0

    with gzip.open(episode_runs_path, "rt", encoding="utf-8") as src:
        for line_no, line in enumerate(src, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            key = key_of(rec)
            sid = assignments.get(key)
            if sid is None:
                raise RuntimeError(f"V22_SHARD_EPISODE_ORPHAN:{line_no}:{key}")
            if sid != active_shard:
                if ep_fh is not None:
                    ep_fh.close()
                if active_shard is not None:
                    closed_shards.add(active_shard)
                if sid in closed_shards:
                    raise RuntimeError(f"V22_SHARD_EPISODE_ORDER_REENTRY:{sid}:{key}")
                active_shard = sid
                ep_fh = gzwrite(output_root / "episode_runs" / f"{sid}.jsonl.gz")
            assert ep_fh is not None
            encoded = canon(rec)
            ep_fh.write(encoded.decode("utf-8"))
            nrows = int(rec.get("row_count", 0))
            meta = shard_meta[sid]
            meta["episode_runs"] += 1
            meta["episode_rows"] += nrows
            meta["_ep"].update(encoded)
            episode_digest.update(encoded)
            episode_keys.add(key)
            acc = source_accounting[key[0]]
            acc["episode_runs"] += 1
            acc["episode_rows"] += nrows
            total_episode_runs += 1
            total_episode_rows += nrows
    if ep_fh is not None:
        ep_fh.close()

    expected_episode_keys = set(assignments) - zero_keys
    missing_episode_keys = expected_episode_keys - episode_keys
    unexpected_zero_episode_keys = episode_keys & zero_keys

    checkpoints: list[dict[str, Any]] = []
    for sid, meta in shard_meta.items():
        checkpoint = {
            "shard_id": sid,
            "source": meta["source"],
            "ticker_days": meta["ticker_days"],
            "minute_rows": meta["minute_rows"],
            "zero_session_ticker_days": meta["zero_session_ticker_days"],
            "episode_runs": meta["episode_runs"],
            "episode_rows": meta["episode_rows"],
            "first_identity": meta["first_identity"],
            "last_identity": meta["last_identity"],
            "identity_digest_sha256": meta["_id"].hexdigest(),
            "ticker_day_digest_sha256": meta["_td"].hexdigest(),
            "episode_run_digest_sha256": meta["_ep"].hexdigest(),
            "pass": meta["episode_rows"] == meta["minute_rows"],
        }
        (output_root / "checkpoints" / f"{sid}.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True), encoding="utf-8")
        checkpoints.append(checkpoint)

    exact = (
        total_td == expected_ticker_days
        and total_rows == expected_minute_rows
        and total_zero == expected_zero_session_ticker_days
        and total_episode_runs == expected_episode_runs
    )
    unique = len(assignments) == total_td
    partition = (
        total_episode_rows == expected_minute_rows
        and not missing_episode_keys
        and not unexpected_zero_episode_keys
        and all(x["pass"] for x in checkpoints)
    )
    status = "PASS" if exact and unique and partition else "FAIL"
    manifest = {
        "schema": SCHEMA,
        "status": status,
        "artifact_digest": artifact_digest,
        "shard_contract": {
            "max_ticker_days_per_shard": shard_ticker_days,
            "source_boundary_never_crossed": True,
            "ticker_day_summary_single_read_pass": True,
            "same_identity_assigned_once": True,
            "zero_session_preserved": True,
            "episode_runs_partition_same_ticker_day": True,
            "reusable_without_raw_or_census_reread": True,
        },
        "expected": {
            "ticker_days": expected_ticker_days,
            "minute_rows": expected_minute_rows,
            "zero_session_ticker_days": expected_zero_session_ticker_days,
            "episode_runs": expected_episode_runs,
        },
        "reconciliation": {
            "ticker_days": total_td,
            "minute_rows_from_ticker_days": total_rows,
            "zero_session_ticker_days": total_zero,
            "episode_runs": total_episode_runs,
            "minute_rows_partitioned_by_episode_runs": total_episode_rows,
            "unique_identities": len(assignments),
            "missing_episode_identity_count": len(missing_episode_keys),
            "unexpected_zero_session_episode_identity_count": len(unexpected_zero_episode_keys),
            "exact_coverage_pass": exact,
            "no_duplicate_identity_pass": unique,
            "episode_partition_pass": partition,
        },
        "digests": {
            "global_identity_sha256": identity_digest.hexdigest(),
            "global_ticker_day_record_sha256": td_digest.hexdigest(),
            "global_episode_run_record_sha256": episode_digest.hexdigest(),
        },
        "source_accounting": source_accounting,
        "shard_count": len(checkpoints),
        "shards": checkpoints,
        "execution": {"reused_existing_pass_manifest": False},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    if status != "PASS":
        raise RuntimeError("V22_DURABLE_SHARD_RECONCILIATION_FAILED")
    return manifest


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ticker-days", required=True)
    p.add_argument("--episode-runs", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--artifact-digest", required=True)
    p.add_argument("--expected-ticker-days", type=int, required=True)
    p.add_argument("--expected-minute-rows", type=int, required=True)
    p.add_argument("--expected-zero-session-ticker-days", type=int, required=True)
    p.add_argument("--expected-episode-runs", type=int, required=True)
    p.add_argument("--shard-ticker-days", type=int, default=5000)
    a = p.parse_args()
    report = run(
        ticker_days_path=Path(a.ticker_days),
        episode_runs_path=Path(a.episode_runs),
        output_root=Path(a.output_root),
        artifact_digest=a.artifact_digest,
        expected_ticker_days=a.expected_ticker_days,
        expected_minute_rows=a.expected_minute_rows,
        expected_zero_session_ticker_days=a.expected_zero_session_ticker_days,
        expected_episode_runs=a.expected_episode_runs,
        shard_ticker_days=a.shard_ticker_days,
    )
    print(json.dumps({"schema": report["schema"], "status": report["status"], "shard_count": report["shard_count"], "reconciliation": report["reconciliation"], "execution": report["execution"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
