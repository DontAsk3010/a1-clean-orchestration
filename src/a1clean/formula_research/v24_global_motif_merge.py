from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "A1_V24_GLOBAL_MOTIF_MERGE_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_key(kind: str, key: str) -> tuple[str, str, str]:
    parts = json.loads(key)
    if kind == "STATE" and len(parts) == 1:
        return str(parts[0]), "", ""
    if kind == "TRANSITION" and len(parts) == 2:
        return str(parts[0]), str(parts[1]), ""
    if kind == "BRANCH3" and len(parts) == 3:
        return str(parts[0]), str(parts[1]), str(parts[2])
    raise RuntimeError(f"V24_BAD_MOTIF_KEY:{kind}:{key}")


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS processed_shards(
          shard_id TEXT PRIMARY KEY,
          fingerprint TEXT NOT NULL,
          output_sha256 TEXT NOT NULL,
          source TEXT NOT NULL,
          committed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS motifs(
          kind TEXT NOT NULL,
          k1 TEXT NOT NULL,
          k2 TEXT NOT NULL,
          k3 TEXT NOT NULL,
          occurrences INTEGER NOT NULL,
          unique_ticker_days INTEGER NOT NULL,
          first_start_timestamp TEXT,
          last_start_timestamp TEXT,
          PRIMARY KEY(kind,k1,k2,k3)
        );
        CREATE TABLE IF NOT EXISTS motif_clock(
          kind TEXT NOT NULL,
          k1 TEXT NOT NULL,
          k2 TEXT NOT NULL,
          k3 TEXT NOT NULL,
          start_clock TEXT NOT NULL,
          occurrences INTEGER NOT NULL,
          PRIMARY KEY(kind,k1,k2,k3,start_clock)
        );
        CREATE TABLE IF NOT EXISTS motif_period(
          kind TEXT NOT NULL,
          k1 TEXT NOT NULL,
          k2 TEXT NOT NULL,
          k3 TEXT NOT NULL,
          block TEXT NOT NULL,
          source TEXT NOT NULL,
          occurrences INTEGER NOT NULL,
          PRIMARY KEY(kind,k1,k2,k3,block,source)
        );
        CREATE INDEX IF NOT EXISTS idx_motifs_kind_occ ON motifs(kind,occurrences DESC);
        CREATE INDEX IF NOT EXISTS idx_period_motif ON motif_period(kind,k1,k2,k3);
        CREATE INDEX IF NOT EXISTS idx_clock_motif ON motif_clock(kind,k1,k2,k3);
        """
    )
    return con


def upsert_motif(con: sqlite3.Connection, kind: str, key: str, rec: Mapping[str, Any]) -> None:
    k1, k2, k3 = parse_key(kind, key)
    con.execute(
        """
        INSERT INTO motifs(kind,k1,k2,k3,occurrences,unique_ticker_days,first_start_timestamp,last_start_timestamp)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(kind,k1,k2,k3) DO UPDATE SET
          occurrences=occurrences+excluded.occurrences,
          unique_ticker_days=unique_ticker_days+excluded.unique_ticker_days,
          first_start_timestamp=CASE
            WHEN motifs.first_start_timestamp IS NULL THEN excluded.first_start_timestamp
            WHEN excluded.first_start_timestamp IS NULL THEN motifs.first_start_timestamp
            WHEN excluded.first_start_timestamp < motifs.first_start_timestamp THEN excluded.first_start_timestamp
            ELSE motifs.first_start_timestamp END,
          last_start_timestamp=CASE
            WHEN motifs.last_start_timestamp IS NULL THEN excluded.last_start_timestamp
            WHEN excluded.last_start_timestamp IS NULL THEN motifs.last_start_timestamp
            WHEN excluded.last_start_timestamp > motifs.last_start_timestamp THEN excluded.last_start_timestamp
            ELSE motifs.last_start_timestamp END
        """,
        (kind, k1, k2, k3, int(rec["occurrences"]), int(rec["unique_ticker_days"]), rec.get("first_start_timestamp"), rec.get("last_start_timestamp")),
    )


def run(*, v23_root: Path, output_root: Path) -> dict[str, Any]:
    v23_manifest_path = v23_root / "manifest.json"
    if not v23_manifest_path.is_file():
        raise RuntimeError("V24_V23_MANIFEST_MISSING")
    v23 = json.loads(v23_manifest_path.read_text(encoding="utf-8"))
    if v23.get("status") != "PASS" or v23.get("reconciliation", {}).get("pass") is not True:
        raise RuntimeError("V24_V23_MANIFEST_NOT_PASS")

    output_root.mkdir(parents=True, exist_ok=True)
    db_path = output_root / "global-motif-registry.sqlite3"
    con = open_db(db_path)
    checkpoints = sorted((v23_root / "checkpoints").glob("*.json"))
    try:
        for cp_path in checkpoints:
            cp = json.loads(cp_path.read_text(encoding="utf-8"))
            if cp.get("status") != "PASS":
                raise RuntimeError(f"V24_BAD_V23_CHECKPOINT:{cp_path.name}")
            sid = str(cp["shard_id"])
            fp = str(cp["fingerprint"])
            out_sha = str(cp["output_sha256"])
            row = con.execute("SELECT fingerprint,output_sha256 FROM processed_shards WHERE shard_id=?", (sid,)).fetchone()
            if row is not None:
                if row[0] != fp or row[1] != out_sha:
                    raise RuntimeError(f"V24_PROCESSED_SHARD_CONFLICT:{sid}")
                continue
            reg_path = v23_root / "registries" / f"{sid}.json.gz"
            if not reg_path.is_file() or sha256_file(reg_path) != out_sha:
                raise RuntimeError(f"V24_REGISTRY_DIGEST_MISMATCH:{sid}")
            with gzip.open(reg_path, "rt", encoding="utf-8") as fh:
                reg = json.load(fh)
            if reg.get("status") != "PASS" or reg.get("fingerprint") != fp:
                raise RuntimeError(f"V24_REGISTRY_NOT_PASS:{sid}")

            con.execute("BEGIN IMMEDIATE")
            try:
                for kind, section in (("STATE", reg["state"]), ("TRANSITION", reg["transition"]), ("BRANCH3", reg["branch3"])):
                    for key, rec in section.items():
                        upsert_motif(con, kind, key, rec)
                for kind, key, minute, occurrences in reg["clock_counts"]:
                    k1, k2, k3 = parse_key(kind, key)
                    con.execute(
                        """INSERT INTO motif_clock(kind,k1,k2,k3,start_clock,occurrences) VALUES(?,?,?,?,?,?)
                           ON CONFLICT(kind,k1,k2,k3,start_clock) DO UPDATE SET occurrences=occurrences+excluded.occurrences""",
                        (kind, k1, k2, k3, minute, int(occurrences)),
                    )
                for kind, key, block, source, occurrences in reg["period_counts"]:
                    k1, k2, k3 = parse_key(kind, key)
                    con.execute(
                        """INSERT INTO motif_period(kind,k1,k2,k3,block,source,occurrences) VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(kind,k1,k2,k3,block,source) DO UPDATE SET occurrences=occurrences+excluded.occurrences""",
                        (kind, k1, k2, k3, block, source, int(occurrences)),
                    )
                con.execute(
                    "INSERT INTO processed_shards(shard_id,fingerprint,output_sha256,source,committed_at) VALUES(?,?,?,?,?)",
                    (sid, fp, out_sha, str(cp["source"]), datetime.now(timezone.utc).isoformat()),
                )
                con.commit()
            except Exception:
                con.rollback()
                raise

        processed = int(con.execute("SELECT COUNT(*) FROM processed_shards").fetchone()[0])
        unique = {kind: int(con.execute("SELECT COUNT(*) FROM motifs WHERE kind=?", (kind,)).fetchone()[0]) for kind in ("STATE", "TRANSITION", "BRANCH3")}
        occurrence = {kind: int(con.execute("SELECT COALESCE(SUM(occurrences),0) FROM motifs WHERE kind=?", (kind,)).fetchone()[0]) for kind in ("STATE", "TRANSITION", "BRANCH3")}
        divergent_prefixes = int(con.execute(
            "SELECT COUNT(*) FROM (SELECT k1,k2 FROM motifs WHERE kind='BRANCH3' GROUP BY k1,k2 HAVING COUNT(*) > 1)"
        ).fetchone()[0])
        single_path_prefixes = int(con.execute(
            "SELECT COUNT(*) FROM (SELECT k1,k2 FROM motifs WHERE kind='BRANCH3' GROUP BY k1,k2 HAVING COUNT(*) = 1)"
        ).fetchone()[0])
        cross_source = {kind: int(con.execute(
            "SELECT COUNT(*) FROM (SELECT k1,k2,k3 FROM motif_period WHERE kind=? GROUP BY k1,k2,k3 HAVING COUNT(DISTINCT source) > 1)",
            (kind,),
        ).fetchone()[0]) for kind in ("STATE", "TRANSITION", "BRANCH3")}
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    finally:
        con.close()

    ok = processed == int(v23["reconciliation"]["shards"]) and occurrence["STATE"] == int(v23["reconciliation"]["episode_runs"])
    result = {
        "schema": SCHEMA,
        "status": "PASS" if ok else "FAIL",
        "research_status": STATUS,
        "input_v23_manifest_sha256": sha256_file(v23_manifest_path),
        "contract": {
            "reads_only_v23_per_shard_registries": True,
            "v22_episode_reread": False,
            "raw_reread": False,
            "census_rerun": False,
            "future_outcome_used_to_define_motif": False,
            "arbitrary_signal_thresholds_added": False,
            "exact_clock_minute_counts_preserved": True,
            "cross_source_counts_preserved": True,
            "branching_prefixes_are_near_twin_candidates_not_winner_labels": True,
        },
        "reconciliation": {
            "processed_shards": processed,
            "expected_shards": int(v23["reconciliation"]["shards"]),
            "state_occurrences": occurrence["STATE"],
            "expected_episode_runs": int(v23["reconciliation"]["episode_runs"]),
            "pass": ok,
        },
        "registry": {
            "sqlite_path": str(db_path),
            "sqlite_sha256": sha256_file(db_path),
            "unique_motifs": unique,
            "occurrences": occurrence,
            "cross_source_motifs": cross_source,
            "divergent_two_state_prefixes": divergent_prefixes,
            "single_path_two_state_prefixes": single_path_prefixes,
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not ok:
        raise RuntimeError("V24_GLOBAL_MERGE_RECONCILIATION_FAILED")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--v23-root", required=True)
    p.add_argument("--output-root", required=True)
    a = p.parse_args()
    result = run(v23_root=Path(a.v23_root), output_root=Path(a.output_root))
    print(json.dumps({"schema": result["schema"], "status": result["status"], "reconciliation": result["reconciliation"], "registry": result["registry"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
