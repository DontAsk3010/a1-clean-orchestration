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


def _canon(obj: Mapping[str, Any]) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return text[:80] or "source"


def _key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(record.get("source") or ""), str(record.get("ticker") or ""), str(record.get("date") or "")


def _key_text(key: tuple[str, str, str]) -> str:
    return "\x1f".join(key)


def _open_gz(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return gzip.open(path, "wt", encoding="utf-8", newline="\n")


def _load_reusable_manifest(path: Path, *, artifact_digest: str, expected_ticker_days: int, expected_minute_rows: int) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if (
        obj.get("schema") == SCHEMA
        and obj.get("status") == "PASS"
        and obj.get("artifact_digest") == artifact_digest
        and int(obj.get("reconciliation", {}).get("ticker_days", -1)) == expected_ticker_days
        and int(obj.get("reconciliation", {}).get("minute_rows_from_ticker_days", -1)) == expected_minute_rows
        and bool(obj.get("reconciliation", {}).get("exact_coverage_pass"))
        and bool(obj.get("reconciliation", {}).get("no_duplicate_identity_pass"))
        and bool(obj.get("reconciliation", {}).get("episode_partition_pass"))
    ):
        return obj
    return None


def shard(
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
    reusable = _load_reusable_manifest(
        manifest_path,
        artifact_digest=artifact_digest,
        expected_ticker_days=expected_ticker_days,
        expected_minute_rows=expected_minute_rows,
    )
    if reusable is not None:
        reusable = dict(reusable)
        reusable["execution"] = {"reused_existing_pass_manifest": True}
        return reusable

    if output_root.exists():
        for child in output_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    (output_root / "ticker_days").mkdir(parents=True, exist_ok=True)
    (output_root / "episode_runs").mkdir(parents=True, exist_ok=True)
    (output_root / "checkpoints").mkdir(parents=True, exist_ok=True)

    assignment: dict[tuple[str, str, str], str] = {}
    seen: set[tuple[str, str, str]] = set()
    shard_meta: dict[str, dict[str, Any]] = {}
    source_seq: dict[str, int] = {}
    source_counts: dict[str, dict[str, int]] = {}
    global_identity_digest = hashlib.sha256()
    global_ticker_day_digest = hashlib.sha256()

    current_source: str | None = None
    current_shard_id: str | None = None
    current_fh = None
    current_count = 0
    total_ticker_days = 0
    total_minute_rows = 0
    total_zero = 0

    def start_shard(source: str) -> tuple[str, Any]:
        seq = source_seq.get(source, 0) + 1
        source_seq[source] = seq
        shard_id = f"{_slug(source)}__{seq:04d}"
        path = output_root / "ticker_days" / f"{shard_id}.jsonl.gz"
        fh = _open_gz(path)
        shard_meta[shard_id] = {
            "shard_id": shard_id,
            "source": source,
            "ticker_day_path": str(path),
            "episode_run_path": str(output_root / "episode_runs" / f"{shard_id}.jsonl.gz"),
            "ticker_days": 0,
            "minute_rows": 0,
            "zero_session_ticker_days": 0,
            "episode_runs": 0,
            "episode_rows": 0,
            "first_identity": None,
            "last_identity": None,
            "ticker_day_digest_sha256": None,
            "episode_run_digest_sha256": None,
            "identity_digest_sha256": None,
            "pass": False,
            "_td_digest": hashlib.sha256(),
            "_ep_digest": hashlib.sha256(),
            "_id_digest": hashlib.sha256(),
        }
        return shard_id, fh

    with gzip.open(ticker_days_path, "rt", encoding="utf-8") as src:
        for line_no, line in enumerate(src, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _key(record)
            if not all(key):
                raise RuntimeError(f"V22_SHARD_INVALID_IDENTITY:{line_no}:{key}")
            if key in seen:
                raise RuntimeError(f"V22_SHARD_DUPLICATE_IDENTITY:{key}")
            seen.add(key)
            source = key[0]
            if current_source != source or current_shard_id is None or current_count >= shard_ticker_days:
                if current_fh is not None:
                    current_fh.close()
                current_source = source
                current_shard_id, current_fh = start_shard(source)
                current_count = 0

            assert current_shard_id is not None and current_fh is not None
            encoded = _canon(record)
            current_fh.write(encoded.decode("utf-8"))
            identity_bytes = (_key_text(key) + "\n").encode("utf-8")
            rows = int(record.get("rows", 0))
            zero = bool(record.get("zero_session_eligible", False)) or rows == 0
            meta = shard_meta[current_shard_id]
            meta["ticker_days"] += 1
            meta["minute_rows"] += rows
            meta["zero_session_ticker_days"] += int(zero)
            meta["first_identity"] = meta["first_identity"] or list(key)
            meta["last_identity"] = list(key)
            meta["_td_digest"].update(encoded)
            meta["_id_digest"].update(identity_bytes)
            global_ticker_day_digest.update(encoded)
            global_identity_digest.update(identity_bytes)
            assignment[key] = current_shard_id
            source_counts.setdefault(source, {"ticker_days": 0, "minute_rows": 0, "zero_session_ticker_days": 0, "episode_runs": 0, "episode_rows": 0})
            source_counts[source]["ticker_days"] += 1
            source_counts[source]["minute_rows"] += rows
            source_counts[source]["zero_session_ticker_days"] += int(zero)
            total_ticker_days += 1
            total_minute_rows += rows
            total_zero += int(zero)
            current_count += 1
    if current_fh is not None:
        current_fh.close()

    global_episode_digest = hashlib.sha256()
    total_episode_runs = 0
    total_episode_rows = 0
    episode_keys_seen: set[tuple[str, str, str]] = set()
    current_episode_shard: str | None = None
    ep_fh = None

    with gzip.open(episode_runs_path, "rt", encoding="utf-8") as src:
        for line_no, line in enumerate(src, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            key = _key(record)
            shard_id = assignment.get(key)
            if shard_id is None:
                raise RuntimeError(f"V22_SHARD_EPISODE_ORPHAN:{line_no}:{key}")
            if current_episode_shard != shard_id:
                if ep_fh is not None:
                    ep_fh.close()
                current_episode_shard = shard_id
                ep_fh = _open_gz(output_root / "episode_runs" / f"{shard_id}.jsonl.gz")
            assert ep_fh is not None
            encoded = _canon(record)
            ep_fh.write(encoded.decode("utf-8"))
            row_count = int(record.get("row_count", 0))
            meta = shard_meta[shard_id]
            meta["episode_runs"] += 1
            meta["episode_rows"] += row_count
            meta["_ep_digest"].update(encoded)
            global_episode_digest.update(encoded)
            source = key[0]
            source_counts[source]["episode_runs"] += 1
            source_counts[source]["episode_rows"] += row_count
            episode_keys_seen.add(key)
            total_episode_runs += 1
            total_episode_rows += row_count
    if ep_fh is not None:
        ep_fh.close()

    nonzero_identities = {k for k in seen if assignment[k] and next((m for m in shard_meta.values() if m["shard_id"] == assignment[k]), None) is not None}
    # Every non-zero ticker-day must have at least one episode run. Zero-session ticker-days may have none.
    zero_keys: set[tuple[str, str, str]] = set()
    with gzip.open(ticker_days_path, "rt", encoding="utf-8") as src:
        for line in src:
            if not line.strip():
                continue
            record = json.loads(line)
            if int(record.get("rows", 0)) == 0 or bool(record.get("zero_session_eligible", False)):
                zero_keys.add(_key(record))
    expected_episode_keys = seen - zero_keys
    missing_episode_keys = expected_episode_keys - episode_keys_seen
    unexpected_zero_episode_keys = episode_keys_seen & zero_keys

    checkpoints: list[dict[str, Any]] = []
    for shard_id, meta in shard_meta.items():
        meta["ticker_day_digest_sha256"] = meta.pop("_td_digest").hexdigest()
        meta["episode_run_digest_sha256"] = meta.pop("_ep_digest").hexdigest()
        meta["identity_digest_sha256"] = meta.pop("_id_digest").hexdigest()
        meta["pass"] = meta["episode_rows"] == meta["minute_rows"]
        checkpoint = {k: v for k, v in meta.items() if not k.endswith("_path")}
        (output_root / "checkpoints" / f"{shard_id}.json").write_text(json.dumps(checkpoint, indent=2, sort_keys=True), encoding="utf-8")
        checkpoints.append(checkpoint)

    exact_coverage_pass = (
        total_ticker_days == expected_ticker_days
        and total_minute_rows == expected_minute_rows
        and total_zero == expected_zero_session_ticker_days
        and total_episode_runs == expected_episode_runs
    )
    no_duplicate_identity_pass = len(seen) == total_ticker_days
    episode_partition_pass = (
        total_episode_rows == expected_minute_rows
        and not missing_episode_keys
        and not unexpected_zero_episode_keys
        and all(bool(x["pass"]) for x in checkpoints)
    )
    status = "PASS" if exact_coverage_pass and no_duplicate_identity_pass and episode_partition_pass else "FAIL"

    manifest = {
        "schema": SCHEMA,
        "status": status,
        "artifact_digest": artifact_digest,
        "shard_contract": {
            "max_ticker_days_per_shard": shard_ticker_days,
            "source_boundary_never_crossed": True,
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
            "ticker_days": total_ticker_days,
            "minute_rows_from_ticker_days": total_minute_rows,
            "zero_session_ticker_days": total_zero,
            "episode_runs": total_episode_runs,
            "minute_rows_partitioned_by_episode_runs": total_episode_rows,
            "unique_identities": len(seen),
            "missing_episode_identity_count": len(missing_episode_keys),
            "unexpected_zero_session_episode_identity_count": len(unexpected_zero_episode_keys),
            "exact_coverage_pass": exact_coverage_pass,
            "no_duplicate_identity_pass": no_duplicate_identity_pass,
            "episode_partition_pass": episode_partition_pass,
        },
        "digests": {
            "global_identity_sha256": global_identity_digest.hexdigest(),
            "global_ticker_day_record_sha256": global_ticker_day_digest.hexdigest(),
            "global_episode_run_record_sha256": global_episode_digest.hexdigest(),
        },
        "source_accounting": source_counts,
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
    report = shard(
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
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "shard_count": report["shard_count"],
        "reconciliation": report["reconciliation"],
        "execution": report["execution"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
