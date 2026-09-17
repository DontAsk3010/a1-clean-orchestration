from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "A1_V25_CAUSAL_DIVERGENCE_ATLAS_V1"
STATUS = "RESEARCH_ONLY_NOT_CANONICAL"

FIELDS = (
    "relation",
    "price_direction",
    "volume_direction",
    "value_direction",
    "flow_direction",
    "flow_effort_change",
    "value_activity_change",
    "fresh_high",
    "fresh_low",
    "haka_haki_dominance",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_token(token: str) -> dict[str, str]:
    parts = token.split("|")
    if len(parts) != 10:
        raise RuntimeError(f"V25_BAD_TOKEN:{token}")
    prefixes = ("P_", "VOL_", "VALUE_", "FLOW_", "FLOWEFF_", "VALACT_", "HI_", "LO_", "HH_")
    for value, prefix in zip(parts[1:], prefixes):
        if not value.startswith(prefix):
            raise RuntimeError(f"V25_BAD_TOKEN_COMPONENT:{prefix}:{token}")
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


def child_sources(con: sqlite3.Connection, k1: str, k2: str, k3: str) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT source FROM motif_period WHERE kind='BRANCH3' AND k1=? AND k2=? AND k3=? ORDER BY source",
        (k1, k2, k3),
    ).fetchall()
    return [str(r[0]) for r in rows]


def child_blocks(con: sqlite3.Connection, k1: str, k2: str, k3: str) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT block FROM motif_period WHERE kind='BRANCH3' AND k1=? AND k2=? AND k3=? ORDER BY block",
        (k1, k2, k3),
    ).fetchall()
    return [str(r[0]) for r in rows]


def child_clocks(con: sqlite3.Connection, k1: str, k2: str, k3: str) -> list[list[Any]]:
    rows = con.execute(
        "SELECT start_clock,occurrences FROM motif_clock WHERE kind='BRANCH3' AND k1=? AND k2=? AND k3=? ORDER BY start_clock",
        (k1, k2, k3),
    ).fetchall()
    return [[str(r[0]), int(r[1])] for r in rows]


def run(*, v24_root: Path, output_root: Path) -> dict[str, Any]:
    manifest_path = v24_root / "manifest.json"
    db_path = v24_root / "global-motif-registry.sqlite3"
    if not manifest_path.is_file() or not db_path.is_file():
        raise RuntimeError("V25_V24_INPUT_MISSING")
    v24 = json.loads(manifest_path.read_text(encoding="utf-8"))
    if v24.get("status") != "PASS" or v24.get("reconciliation", {}).get("pass") is not True:
        raise RuntimeError("V25_V24_NOT_PASS")
    expected_db_sha = str(v24.get("registry", {}).get("sqlite_sha256") or "")
    if expected_db_sha and sha256_file(db_path) != expected_db_sha:
        raise RuntimeError("V25_V24_DB_DIGEST_MISMATCH")

    output_root.mkdir(parents=True, exist_ok=True)
    atlas_path = output_root / "causal-divergence-atlas.jsonl.gz"
    candidates_path = output_root / "candidate-state-machine-fragments.jsonl.gz"
    tmp_atlas = atlas_path.with_suffix(atlas_path.suffix + ".tmp")
    tmp_candidates = candidates_path.with_suffix(candidates_path.suffix + ".tmp")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    prefix_count = 0
    child_count = 0
    portable_prefixes = 0
    dimension_counts: Counter[str] = Counter()
    branch_cardinality = Counter()
    exact_relation_pairs = Counter()
    exact_price_pairs = Counter()

    try:
        prefixes = con.execute(
            """
            SELECT k1,k2,COUNT(*) AS n_children,SUM(occurrences) AS prefix_occurrences
            FROM motifs
            WHERE kind='BRANCH3'
            GROUP BY k1,k2
            HAVING COUNT(*) > 1
            ORDER BY k1,k2
            """
        )
        with gzip.open(tmp_atlas, "wt", encoding="utf-8", newline="\n") as atlas_fh, gzip.open(tmp_candidates, "wt", encoding="utf-8", newline="\n") as cand_fh:
            for pref in prefixes:
                k1 = str(pref["k1"])
                k2 = str(pref["k2"])
                rows = con.execute(
                    """
                    SELECT k3,occurrences,unique_ticker_days,first_start_timestamp,last_start_timestamp
                    FROM motifs
                    WHERE kind='BRANCH3' AND k1=? AND k2=?
                    ORDER BY k3
                    """,
                    (k1, k2),
                ).fetchall()
                if len(rows) <= 1:
                    raise RuntimeError("V25_DIVERGENT_PREFIX_COLLAPSED")

                children: list[dict[str, Any]] = []
                values: dict[str, set[str]] = defaultdict(set)
                cross_source_children = 0
                for row in rows:
                    k3 = str(row["k3"])
                    sem = parse_token(k3)
                    sources = child_sources(con, k1, k2, k3)
                    blocks = child_blocks(con, k1, k2, k3)
                    clocks = child_clocks(con, k1, k2, k3)
                    for field, value in sem.items():
                        values[field].add(value)
                    cross_source = len(sources) > 1
                    cross_source_children += int(cross_source)
                    child = {
                        "state": k3,
                        "semantics": sem,
                        "occurrences": int(row["occurrences"]),
                        "unique_ticker_days": int(row["unique_ticker_days"]),
                        "first_start_timestamp": row["first_start_timestamp"],
                        "last_start_timestamp": row["last_start_timestamp"],
                        "sources": sources,
                        "blocks": blocks,
                        "clock_counts": clocks,
                        "cross_source": cross_source,
                    }
                    children.append(child)
                    child_count += 1
                    cand_fh.write(json.dumps({
                        "schema": SCHEMA,
                        "detection_moment": "THIRD_STATE_START",
                        "prefix": [k1, k2],
                        "observed_next_state": k3,
                        "next_state_semantics": sem,
                        "observed_support": {
                            "occurrences": child["occurrences"],
                            "unique_ticker_days": child["unique_ticker_days"],
                            "sources": sources,
                            "blocks": blocks,
                            "cross_source": cross_source,
                        },
                        "formula_role": "CAUSAL_BRANCH_FRAGMENT_NOT_YET_PROMOTED",
                        "future_outcome_used": False,
                    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")

                variable_dimensions = [f for f in FIELDS if len(values[f]) > 1]
                for field in variable_dimensions:
                    dimension_counts[field] += 1
                branch_cardinality[str(len(children))] += 1
                portable = cross_source_children >= 2
                portable_prefixes += int(portable)

                relation_values = sorted(values["relation"])
                price_values = sorted(values["price_direction"])
                if len(relation_values) > 1:
                    exact_relation_pairs[json.dumps(relation_values, separators=(",", ":"))] += 1
                if len(price_values) > 1:
                    exact_price_pairs[json.dumps(price_values, separators=(",", ":"))] += 1

                atlas_fh.write(json.dumps({
                    "schema": SCHEMA,
                    "prefix": [k1, k2],
                    "prefix_occurrences": int(pref["prefix_occurrences"]),
                    "branch_count": len(children),
                    "variable_dimensions": variable_dimensions,
                    "portable_cross_source": portable,
                    "children": children,
                    "causal_interpretation": "same_exact_two_state_prefix_then_first_observed_branch_state_differs",
                    "winner_failure_label_assigned": False,
                }, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
                prefix_count += 1
    finally:
        con.close()

    tmp_atlas.replace(atlas_path)
    tmp_candidates.replace(candidates_path)

    expected_prefixes = int(v24["registry"]["divergent_two_state_prefixes"])
    expected_children = int(v24["registry"]["unique_motifs"]["BRANCH3"])
    single_path = int(v24["registry"]["single_path_two_state_prefixes"])
    expected_divergent_children = expected_children - single_path
    ok = prefix_count == expected_prefixes and child_count == expected_divergent_children

    result = {
        "schema": SCHEMA,
        "status": "PASS" if ok else "FAIL",
        "research_status": STATUS,
        "input_v24_manifest_sha256": sha256_file(manifest_path),
        "input_v24_db_sha256": sha256_file(db_path),
        "contract": {
            "reads_only_v24_global_registry": True,
            "raw_reread": False,
            "census_rerun": False,
            "v22_episode_reread": False,
            "v23_shard_reread": False,
            "future_outcome_used_to_define_divergence": False,
            "arbitrary_numeric_thresholds_added": False,
            "divergence_known_at_third_state_start": True,
            "winner_failure_outcome_not_assigned_yet": True,
        },
        "reconciliation": {
            "divergent_prefixes": prefix_count,
            "expected_divergent_prefixes": expected_prefixes,
            "divergent_child_motifs": child_count,
            "expected_divergent_child_motifs": expected_divergent_children,
            "pass": ok,
        },
        "atlas": {
            "portable_cross_source_prefixes": portable_prefixes,
            "variable_dimension_prefix_counts": dict(sorted(dimension_counts.items())),
            "branch_cardinality_counts": dict(sorted(branch_cardinality.items(), key=lambda x: int(x[0]))),
            "relation_value_set_counts": dict(sorted(exact_relation_pairs.items())),
            "price_direction_value_set_counts": dict(sorted(exact_price_pairs.items())),
            "atlas_path": str(atlas_path),
            "atlas_sha256": sha256_file(atlas_path),
            "candidate_fragments_path": str(candidates_path),
            "candidate_fragments_sha256": sha256_file(candidates_path),
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if not ok:
        raise RuntimeError("V25_RECONCILIATION_FAILED")
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--v24-root", required=True)
    p.add_argument("--output-root", required=True)
    a = p.parse_args()
    result = run(v24_root=Path(a.v24_root), output_root=Path(a.output_root))
    print(json.dumps({"schema": result["schema"], "status": result["status"], "reconciliation": result["reconciliation"], "atlas": result["atlas"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
