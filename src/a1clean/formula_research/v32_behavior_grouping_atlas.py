from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from .full_chronological_cache_catalog import FULL_CHRONOLOGICAL_SOURCE_NAMES

SCHEMA = "A1_V32_BEHAVIOR_GROUPING_ATLAS_V1"
SEMANTIC_SCHEMA = "A1_V32_FULL_OBSERVATION_SEMANTIC_ENRICHMENT_V3"
STATUS = "PROVISIONAL_BEHAVIOR_ATLAS"
FORMULA_STAGE = "CLOSED"
AXIS_VERSION = "M2_MULTI_AXIS_EXACT_SIGNATURE_V1"

STATE_FIELDS = (
    "price_direction",
    "volume_direction",
    "value_direction",
    "flow_direction",
    "flow_effort_change",
    "value_activity_change",
    "bar_range_change",
    "flow_price_relation",
    "fresh_high",
    "fresh_low",
    "open_state",
    "haka_haki_dominance",
)

SEMANTIC_GAP_IDS = ("B04", "B05", "B06", "B07", "B09", "B10", "B11", "B12", "B15")


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _slug(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _iter_gz_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _checkpoint_digest(path: Path) -> str:
    return _sha_file(path)


def _clock(value: Any) -> str:
    raw = str(value or "")
    if "T" in raw:
        raw = raw.split("T", 1)[1]
    elif " " in raw:
        raw = raw.split(" ", 1)[1]
    return raw.replace("Z", "") or "UNKNOWN"


def _compress(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    sentinel = object()
    prev: Any = sentinel
    for value in values:
        normalized = "UNKNOWN" if value is None else value
        if prev is sentinel or normalized != prev:
            out.append(normalized)
            prev = normalized
    return out


def _signature(axis: str, payload: Any) -> tuple[str, str]:
    sig = _canon(payload)
    return _sha_text(axis + "\x1f" + sig), sig


def _state_path(path_rec: Mapping[str, Any], field: str) -> list[Any]:
    return _compress(
        (dict(run.get("state") or {}).get(field) for run in path_rec.get("formation_run_path") or [])
    )


def _full_state_path(path_rec: Mapping[str, Any]) -> list[str]:
    return [str(run.get("state_key") or "UNKNOWN") for run in path_rec.get("formation_run_path") or []]


def _transition_dimension_path(path_rec: Mapping[str, Any]) -> list[list[str]]:
    out: list[list[str]] = []
    for trans in path_rec.get("state_transitions") or []:
        changed = dict(trans.get("changed_dimensions") or {})
        out.append(sorted(str(x) for x in changed))
    return out


def _availability_signature(td: Mapping[str, Any]) -> dict[str, str]:
    availability = dict(td.get("availability") or {})
    return {str(k): str(v) for k, v in sorted(availability.items())}


def _phase_presence(td: Mapping[str, Any]) -> list[str]:
    counts = dict(td.get("source_phase_counts") or {})
    return sorted(str(k) for k, v in counts.items() if int(v or 0) > 0)


def _day_axes(path_rec: Mapping[str, Any], td: Mapping[str, Any]) -> dict[str, Any]:
    refs = list(path_rec.get("lifecycle_journey_refs") or [])
    axes: dict[str, Any] = {
        "FULL_STATE_SEQUENCE": _full_state_path(path_rec),
        "PRICE_PATH": _state_path(path_rec, "price_direction"),
        "VOLUME_PATH": _state_path(path_rec, "volume_direction"),
        "VALUE_PATH": _state_path(path_rec, "value_direction"),
        "FLOW_DIRECTION_PATH": _state_path(path_rec, "flow_direction"),
        "FLOW_EFFORT_PATH": _state_path(path_rec, "flow_effort_change"),
        "FLOW_PRICE_RESPONSE_PATH": _state_path(path_rec, "flow_price_relation"),
        "RANGE_PATH": _state_path(path_rec, "bar_range_change"),
        "OPEN_STATE_PATH": _state_path(path_rec, "open_state"),
        "HAKA_HAKI_PATH": _state_path(path_rec, "haka_haki_dominance"),
        "FRESH_EXTREME_PATH": _compress(
            (
                [bool(dict(run.get("state") or {}).get("fresh_high")), bool(dict(run.get("state") or {}).get("fresh_low"))]
                for run in path_rec.get("formation_run_path") or []
            )
        ),
        "TRANSITION_DIMENSION_PATH": _transition_dimension_path(path_rec),
        "JOURNEY_KIND_SEQUENCE": [str(x.get("journey_kind") or "UNKNOWN") for x in refs],
        "CENSOR_STATE_SEQUENCE": [bool(x.get("right_censored_open")) for x in refs],
        "NO_FORCED_EVENT_STATE": bool(path_rec.get("no_forced_event")),
        "EVIDENCE_AVAILABILITY": _availability_signature(td),
        "SOURCE_PHASE_PRESENCE": _phase_presence(td),
        "CROSS_DATE_CARRY_PRESENT": bool(path_rec.get("prior_condition_carry")),
        "SOURCE_TERMINAL_PHASE": str(
            (path_rec.get("last_source_supported_observation") or {}).get("source_phase") or "UNKNOWN"
        ),
    }
    return axes


def _lifecycle_axes(rec: Mapping[str, Any]) -> tuple[dict[str, Any], str, str, str]:
    formation = [
        {
            "role": str(x.get("role") or "UNKNOWN"),
            "state_key": str(x.get("state_key") or "UNKNOWN"),
        }
        for x in rec.get("formation_sequence") or []
    ]
    resolution = str((rec.get("hindsight_resolution") or {}).get("resolution_status") or "UNKNOWN")
    right_censored = bool(rec.get("right_censored_open"))
    causal_axes: dict[str, Any] = {
        "JOURNEY_KIND": str(rec.get("journey_kind") or "UNKNOWN"),
        "JOURNEY_DIRECTIONAL_ROLE": str(rec.get("directional_role") or "UNKNOWN"),
        "JOURNEY_FORMATION_SEQUENCE": formation,
        "JOURNEY_EVENT_START_CLOCK": _clock((rec.get("timing") or {}).get("event_start_time")),
        "JOURNEY_OPEN_CENSOR_STATE": right_censored,
    }
    formation_id, formation_json = _signature("JOURNEY_FORMATION_SEQUENCE", formation)
    return causal_axes, formation_id, formation_json, resolution


def _validate_input_file(source_dir: Path, cp: Mapping[str, Any], role: str) -> Path:
    output_files = dict(cp.get("output_files") or {})
    meta = dict(output_files.get(role) or {})
    name = str(meta.get("name") or "")
    if not name:
        raise RuntimeError(f"M2_GROUP_INPUT_ROLE_MISSING:{cp.get('source')}:{role}")
    path = source_dir / name
    if not path.is_file():
        raise RuntimeError(f"M2_GROUP_INPUT_FILE_MISSING:{cp.get('source')}:{role}:{path}")
    expected_bytes = int(meta.get("bytes", -1))
    if expected_bytes < 0 or path.stat().st_size != expected_bytes:
        raise RuntimeError(f"M2_GROUP_INPUT_BYTES_DRIFT:{cp.get('source')}:{role}")
    expected_sha = str(meta.get("sha256") or "")
    if not expected_sha or _sha_file(path) != expected_sha:
        raise RuntimeError(f"M2_GROUP_INPUT_SHA_DRIFT:{cp.get('source')}:{role}")
    return path


def _load_pass_checkpoint(semantic_root: Path, source: str, software_revision: str) -> tuple[Path, dict[str, Any], str] | None:
    source_dir = semantic_root / _slug(source)
    cp_path = source_dir / "checkpoint.json"
    if not cp_path.is_file():
        return None
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    if str(cp.get("status")) != "PASS":
        return None
    if str(cp.get("schema")) != SEMANTIC_SCHEMA:
        raise RuntimeError(f"M2_GROUP_CHECKPOINT_SCHEMA_DRIFT:{source}:{cp.get('schema')}")
    if str(cp.get("source")) != source:
        raise RuntimeError(f"M2_GROUP_CHECKPOINT_SOURCE_DRIFT:{source}:{cp.get('source')}")
    if str(cp.get("software_revision")) != software_revision:
        raise RuntimeError(
            f"M2_GROUP_CHECKPOINT_SOFTWARE_REVISION_DRIFT:{source}:{cp.get('software_revision')}:{software_revision}"
        )
    return source_dir, cp, _checkpoint_digest(cp_path)


def _init_contribution_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute(
        "CREATE TABLE groups(axis TEXT, group_id TEXT, signature_json TEXT, member_count INTEGER, "
        "PRIMARY KEY(axis, group_id))"
    )
    db.execute(
        "CREATE TABLE near_twin_outcomes(formation_group_id TEXT, formation_signature_json TEXT, "
        "resolution_status TEXT, member_count INTEGER, PRIMARY KEY(formation_group_id, resolution_status))"
    )
    return db


def _flush_counts(db: sqlite3.Connection, groups: Counter[tuple[str, str, str]], near: Counter[tuple[str, str, str]]) -> None:
    if groups:
        db.executemany(
            "INSERT INTO groups(axis,group_id,signature_json,member_count) VALUES(?,?,?,?) "
            "ON CONFLICT(axis,group_id) DO UPDATE SET member_count=member_count+excluded.member_count",
            ((a, gid, sig, int(n)) for (a, gid, sig), n in groups.items()),
        )
        groups.clear()
    if near:
        db.executemany(
            "INSERT INTO near_twin_outcomes(formation_group_id,formation_signature_json,resolution_status,member_count) "
            "VALUES(?,?,?,?) ON CONFLICT(formation_group_id,resolution_status) DO UPDATE SET "
            "member_count=member_count+excluded.member_count",
            ((gid, sig, status, int(n)) for (gid, sig, status), n in near.items()),
        )
        near.clear()


def _build_contribution(
    *,
    source: str,
    source_order: int,
    source_dir: Path,
    cp: Mapping[str, Any],
    cp_digest: str,
    contribution_dir: Path,
) -> dict[str, Any]:
    contribution_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = contribution_dir / "contribution-manifest.json"
    db_path = contribution_dir / "contribution.sqlite3"
    day_members_path = contribution_dir / "day-members.jsonl.gz"
    journey_members_path = contribution_dir / "journey-members.jsonl.gz"
    if manifest_path.is_file() and db_path.is_file() and day_members_path.is_file() and journey_members_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(existing.get("checkpoint_digest_sha256")) == cp_digest:
            return existing
        raise RuntimeError(f"M2_GROUP_EXISTING_CONTRIBUTION_DIGEST_DRIFT:{source}")

    ticker_path = _validate_input_file(source_dir, cp, "ticker_days")
    behavior_path = _validate_input_file(source_dir, cp, "behavior_paths")
    lifecycle_path = _validate_input_file(source_dir, cp, "behavior_lifecycle")

    td_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for td in _iter_gz_jsonl(ticker_path):
        td_by_key[(str(td.get("ticker")), str(td.get("date")))] = td
    expected_days = int(cp.get("ticker_days", -1))
    if len(td_by_key) != expected_days:
        raise RuntimeError(f"M2_GROUP_TICKER_DAY_INDEX_COUNT_FAIL:{source}:{len(td_by_key)}:{expected_days}")

    tmp_db = db_path.with_suffix(".sqlite3.tmp")
    tmp_day = day_members_path.with_suffix(day_members_path.suffix + ".tmp")
    tmp_journey = journey_members_path.with_suffix(journey_members_path.suffix + ".tmp")
    for p in (tmp_db, tmp_day, tmp_journey):
        if p.exists():
            p.unlink()
    cdb = _init_contribution_db(tmp_db)
    group_counts: Counter[tuple[str, str, str]] = Counter()
    near_counts: Counter[tuple[str, str, str]] = Counter()
    day_count = 0
    journey_count = 0

    try:
        with gzip.open(tmp_day, "wt", encoding="utf-8", newline="\n") as day_fh:
            for path_rec in _iter_gz_jsonl(behavior_path):
                key = (str(path_rec.get("ticker")), str(path_rec.get("date")))
                td = td_by_key.get(key)
                if td is None:
                    raise RuntimeError(f"M2_GROUP_BEHAVIOR_PATH_ORPHAN:{source}:{key}")
                axes = _day_axes(path_rec, td)
                memberships: dict[str, str] = {}
                for axis, payload in axes.items():
                    gid, sig = _signature(axis, payload)
                    memberships[axis] = gid
                    group_counts[(axis, gid, sig)] += 1
                day_fh.write(
                    _canon(
                        {
                            "schema": SCHEMA,
                            "source": source,
                            "source_order": source_order,
                            "ticker": key[0],
                            "date": key[1],
                            "causal_group_memberships": memberships,
                            "no_forced_event": bool(path_rec.get("no_forced_event")),
                            "formula_stage": FORMULA_STAGE,
                        }
                    )
                    + "\n"
                )
                day_count += 1
                if day_count % 50000 == 0:
                    _flush_counts(cdb, group_counts, near_counts)
                    cdb.commit()

        with gzip.open(tmp_journey, "wt", encoding="utf-8", newline="\n") as journey_fh:
            for rec in _iter_gz_jsonl(lifecycle_path):
                axes, formation_id, formation_sig, resolution = _lifecycle_axes(rec)
                memberships: dict[str, str] = {}
                for axis, payload in axes.items():
                    gid, sig = _signature(axis, payload)
                    memberships[axis] = gid
                    group_counts[(axis, gid, sig)] += 1
                resolution_gid, resolution_sig = _signature("HINDSIGHT_RESOLUTION_STATUS", resolution)
                group_counts[("HINDSIGHT_RESOLUTION_STATUS", resolution_gid, resolution_sig)] += 1
                combined_payload = {"formation_group_id": formation_id, "resolution_status": resolution}
                combined_gid, combined_sig = _signature("FORMATION_X_HINDSIGHT_RESOLUTION", combined_payload)
                group_counts[("FORMATION_X_HINDSIGHT_RESOLUTION", combined_gid, combined_sig)] += 1
                near_counts[(formation_id, formation_sig, resolution)] += 1
                journey_fh.write(
                    _canon(
                        {
                            "schema": SCHEMA,
                            "source": source,
                            "source_order": source_order,
                            "ticker": rec.get("ticker"),
                            "date": rec.get("date"),
                            "journey_id": rec.get("journey_id"),
                            "journey_ordinal": rec.get("journey_ordinal"),
                            "causal_group_memberships": memberships,
                            "formation_group_id": formation_id,
                            "hindsight_resolution_group_id": resolution_gid,
                            "formation_x_hindsight_resolution_group_id": combined_gid,
                            "hindsight_resolution_status": resolution,
                            "right_censored_open": bool(rec.get("right_censored_open")),
                            "causal_and_hindsight_kept_separate": True,
                            "formula_stage": FORMULA_STAGE,
                        }
                    )
                    + "\n"
                )
                journey_count += 1
                if journey_count % 50000 == 0:
                    _flush_counts(cdb, group_counts, near_counts)
                    cdb.commit()

        _flush_counts(cdb, group_counts, near_counts)
        cdb.commit()
    finally:
        cdb.close()

    expected_paths = int(cp.get("behavior_paths", expected_days))
    expected_journeys = int(cp.get("behavior_lifecycle_journeys", -1))
    if day_count != expected_paths:
        raise RuntimeError(f"M2_GROUP_DAY_MEMBERSHIP_COUNT_FAIL:{source}:{day_count}:{expected_paths}")
    if journey_count != expected_journeys:
        raise RuntimeError(f"M2_GROUP_JOURNEY_MEMBERSHIP_COUNT_FAIL:{source}:{journey_count}:{expected_journeys}")

    os.replace(tmp_db, db_path)
    os.replace(tmp_day, day_members_path)
    os.replace(tmp_journey, journey_members_path)
    manifest = {
        "schema": SCHEMA,
        "status": "PASS_SOURCE_CONTRIBUTION",
        "atlas_status": STATUS,
        "source": source,
        "source_order": source_order,
        "semantic_checkpoint_digest_sha256": cp_digest,
        "checkpoint_digest_sha256": cp_digest,
        "semantic_software_revision": cp.get("software_revision"),
        "source_drive_id": cp.get("source_drive_id"),
        "source_sha256": cp.get("source_sha256"),
        "ticker_day_memberships": day_count,
        "journey_memberships": journey_count,
        "semantic_gaps_still_open": list(SEMANTIC_GAP_IDS),
        "machine1_labels_used": False,
        "arbitrary_thresholds_added": False,
        "missing_as_zero": False,
        "formula_stage": FORMULA_STAGE,
        "files": {
            "contribution_db": {"name": db_path.name, "sha256": _sha_file(db_path), "bytes": db_path.stat().st_size},
            "day_members": {"name": day_members_path.name, "sha256": _sha_file(day_members_path), "bytes": day_members_path.stat().st_size},
            "journey_members": {"name": journey_members_path.name, "sha256": _sha_file(journey_members_path), "bytes": journey_members_path.stat().st_size},
        },
    }
    _atomic_json(manifest_path, manifest)
    return manifest


def _init_atlas_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute(
        "CREATE TABLE IF NOT EXISTS source_registry(source TEXT PRIMARY KEY, source_order INTEGER UNIQUE, "
        "checkpoint_digest TEXT, contribution_manifest_sha256 TEXT, ticker_day_memberships INTEGER, "
        "journey_memberships INTEGER, applied_at_unix INTEGER)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS groups(axis TEXT, group_id TEXT, signature_json TEXT, member_count INTEGER, "
        "source_count INTEGER, first_source_order INTEGER, last_source_order INTEGER, PRIMARY KEY(axis,group_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS group_sources(axis TEXT, group_id TEXT, source TEXT, member_count INTEGER, "
        "PRIMARY KEY(axis,group_id,source))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS near_twin_outcomes(formation_group_id TEXT, formation_signature_json TEXT, "
        "resolution_status TEXT, member_count INTEGER, source_count INTEGER, first_source_order INTEGER, "
        "last_source_order INTEGER, PRIMARY KEY(formation_group_id,resolution_status))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS near_twin_sources(formation_group_id TEXT, resolution_status TEXT, source TEXT, "
        "member_count INTEGER, PRIMARY KEY(formation_group_id,resolution_status,source))"
    )
    db.commit()
    return db


def _consumed(db: sqlite3.Connection) -> list[tuple[str, int, str]]:
    return [
        (str(r[0]), int(r[1]), str(r[2]))
        for r in db.execute("SELECT source,source_order,checkpoint_digest FROM source_registry ORDER BY source_order")
    ]


def _assert_prefix(consumed: list[tuple[str, int, str]]) -> None:
    expected = list(FULL_CHRONOLOGICAL_SOURCE_NAMES[: len(consumed)])
    actual = [x[0] for x in consumed]
    if actual != expected or any(order != i for i, (_, order, _) in enumerate(consumed)):
        raise RuntimeError(f"M2_GROUP_SOURCE_REGISTRY_NOT_CHRONOLOGICAL_PREFIX:{actual}")


def _apply_contribution(
    db: sqlite3.Connection,
    *,
    source: str,
    source_order: int,
    cp_digest: str,
    contribution_dir: Path,
    manifest: Mapping[str, Any],
) -> None:
    current = db.execute("SELECT checkpoint_digest FROM source_registry WHERE source=?", (source,)).fetchone()
    if current:
        if str(current[0]) != cp_digest:
            raise RuntimeError(f"M2_GROUP_CONSUMED_SOURCE_DIGEST_DRIFT:{source}")
        return
    cdb = sqlite3.connect(contribution_dir / "contribution.sqlite3")
    manifest_sha = _sha_file(contribution_dir / "contribution-manifest.json")
    try:
        db.execute("BEGIN IMMEDIATE")
        for axis, gid, sig, count in cdb.execute("SELECT axis,group_id,signature_json,member_count FROM groups"):
            db.execute(
                "INSERT INTO groups(axis,group_id,signature_json,member_count,source_count,first_source_order,last_source_order) "
                "VALUES(?,?,?,?,1,?,?) ON CONFLICT(axis,group_id) DO UPDATE SET "
                "member_count=member_count+excluded.member_count, source_count=source_count+1, "
                "first_source_order=MIN(first_source_order,excluded.first_source_order), "
                "last_source_order=MAX(last_source_order,excluded.last_source_order)",
                (axis, gid, sig, int(count), source_order, source_order),
            )
            db.execute(
                "INSERT INTO group_sources(axis,group_id,source,member_count) VALUES(?,?,?,?)",
                (axis, gid, source, int(count)),
            )
        for gid, sig, resolution, count in cdb.execute(
            "SELECT formation_group_id,formation_signature_json,resolution_status,member_count FROM near_twin_outcomes"
        ):
            db.execute(
                "INSERT INTO near_twin_outcomes(formation_group_id,formation_signature_json,resolution_status,member_count,"
                "source_count,first_source_order,last_source_order) VALUES(?,?,?,?,1,?,?) "
                "ON CONFLICT(formation_group_id,resolution_status) DO UPDATE SET member_count=member_count+excluded.member_count, "
                "source_count=source_count+1, first_source_order=MIN(first_source_order,excluded.first_source_order), "
                "last_source_order=MAX(last_source_order,excluded.last_source_order)",
                (gid, sig, resolution, int(count), source_order, source_order),
            )
            db.execute(
                "INSERT INTO near_twin_sources(formation_group_id,resolution_status,source,member_count) VALUES(?,?,?,?)",
                (gid, resolution, source, int(count)),
            )
        db.execute(
            "INSERT INTO source_registry(source,source_order,checkpoint_digest,contribution_manifest_sha256,"
            "ticker_day_memberships,journey_memberships,applied_at_unix) VALUES(?,?,?,?,?,?,?)",
            (
                source,
                source_order,
                cp_digest,
                manifest_sha,
                int(manifest.get("ticker_day_memberships", 0)),
                int(manifest.get("journey_memberships", 0)),
                int(time.time()),
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cdb.close()


def _export_atlas(db: sqlite3.Connection, output_root: Path, software_revision: str) -> dict[str, Any]:
    consumed = _consumed(db)
    _assert_prefix(consumed)
    registry = [
        {
            "source": r[0],
            "source_order": int(r[1]),
            "checkpoint_digest_sha256": r[2],
            "contribution_manifest_sha256": r[3],
            "ticker_day_memberships": int(r[4]),
            "journey_memberships": int(r[5]),
            "applied_at_unix": int(r[6]),
        }
        for r in db.execute(
            "SELECT source,source_order,checkpoint_digest,contribution_manifest_sha256,ticker_day_memberships,"
            "journey_memberships,applied_at_unix FROM source_registry ORDER BY source_order"
        )
    ]
    axis_summary = [
        {"axis": str(a), "group_count": int(gc), "member_count": int(mc), "source_membership_sum": int(sc)}
        for a, gc, mc, sc in db.execute(
            "SELECT axis,COUNT(*),SUM(member_count),SUM(source_count) FROM groups GROUP BY axis ORDER BY axis"
        )
    ]
    groups_path = output_root / "provisional-group-registry.jsonl.gz"
    groups_tmp = groups_path.with_suffix(groups_path.suffix + ".tmp")
    with gzip.open(groups_tmp, "wt", encoding="utf-8", newline="\n") as fh:
        for row in db.execute(
            "SELECT axis,group_id,signature_json,member_count,source_count,first_source_order,last_source_order "
            "FROM groups ORDER BY axis,group_id"
        ):
            fh.write(
                _canon(
                    {
                        "schema": SCHEMA,
                        "atlas_status": STATUS,
                        "axis": row[0],
                        "group_id": row[1],
                        "signature": json.loads(row[2]),
                        "member_count": int(row[3]),
                        "source_count": int(row[4]),
                        "first_source_order": int(row[5]),
                        "last_source_order": int(row[6]),
                    }
                )
                + "\n"
            )
    os.replace(groups_tmp, groups_path)

    near_path = output_root / "near-twin-outcome-divergence-candidates.jsonl.gz"
    near_tmp = near_path.with_suffix(near_path.suffix + ".tmp")
    with gzip.open(near_tmp, "wt", encoding="utf-8", newline="\n") as fh:
        query = """
            SELECT n.formation_group_id,n.formation_signature_json,n.resolution_status,n.member_count,n.source_count
            FROM near_twin_outcomes n
            JOIN (
                SELECT formation_group_id FROM near_twin_outcomes
                GROUP BY formation_group_id HAVING COUNT(DISTINCT resolution_status) > 1
            ) d ON d.formation_group_id=n.formation_group_id
            ORDER BY n.formation_group_id,n.resolution_status
        """
        for row in db.execute(query):
            fh.write(
                _canon(
                    {
                        "schema": SCHEMA,
                        "candidate_kind": "SAME_CAUSAL_FORMATION_MULTIPLE_LATER_RESOLUTIONS",
                        "formation_group_id": row[0],
                        "causal_formation_signature": json.loads(row[1]),
                        "hindsight_resolution_status": row[2],
                        "member_count": int(row[3]),
                        "source_count": int(row[4]),
                        "future_outcome_not_used_to_define_causal_group": True,
                    }
                )
                + "\n"
            )
    os.replace(near_tmp, near_path)

    near_family_count = int(
        db.execute(
            "SELECT COUNT(*) FROM (SELECT formation_group_id FROM near_twin_outcomes GROUP BY formation_group_id "
            "HAVING COUNT(DISTINCT resolution_status)>1)"
        ).fetchone()[0]
    )
    manifest = {
        "schema": SCHEMA,
        "status": STATUS,
        "axis_version": AXIS_VERSION,
        "semantic_software_revision": software_revision,
        "source_count_consumed": len(registry),
        "source_count_total": len(FULL_CHRONOLOGICAL_SOURCE_NAMES),
        "consumed_sources": [x["source"] for x in registry],
        "latest_consumed_source": registry[-1]["source"] if registry else None,
        "ticker_day_memberships": sum(x["ticker_day_memberships"] for x in registry),
        "journey_memberships": sum(x["journey_memberships"] for x in registry),
        "axis_summary": axis_summary,
        "near_twin_divergence_formation_group_count": near_family_count,
        "automatic_existing_signature_matching": True,
        "automatic_new_signature_creation": True,
        "source_checkpoint_digest_bound": True,
        "consumed_source_digest_drift_policy": "HARD_HOLD_NO_SILENT_REMAP",
        "only_durable_semantic_pass_sources_consumed": True,
        "machine": "MACHINE_2",
        "machine1_semantic_reader_independent": True,
        "machine1_labels_used_as_hidden_targets": False,
        "semantic_gaps_still_open": list(SEMANTIC_GAP_IDS),
        "full_machine1_semantic_parity_claimed": False,
        "missing_as_zero": False,
        "arbitrary_thresholds_added": False,
        "formula_stage": FORMULA_STAGE,
        "research_only_not_canonical": True,
        "group_registry_file": groups_path.name,
        "group_registry_sha256": _sha_file(groups_path),
        "near_twin_candidates_file": near_path.name,
        "near_twin_candidates_sha256": _sha_file(near_path),
    }
    _atomic_json(output_root / "source-consumption-registry.json", registry)
    _atomic_json(output_root / "axis-summary.json", axis_summary)
    _atomic_json(output_root / "manifest.json", manifest)
    _atomic_json(
        output_root / "current-checkpoint.json",
        {
            "schema": SCHEMA,
            "status": STATUS,
            "source_count_consumed": len(registry),
            "latest_consumed_source": manifest["latest_consumed_source"],
            "next_source": (
                FULL_CHRONOLOGICAL_SOURCE_NAMES[len(registry)]
                if len(registry) < len(FULL_CHRONOLOGICAL_SOURCE_NAMES)
                else None
            ),
            "formula_stage": FORMULA_STAGE,
        },
    )
    return manifest


def run_once(
    *,
    semantic_root: Path,
    output_root: Path,
    software_revision: str,
    bootstrap_source_count: int,
) -> dict[str, Any]:
    if not 1 <= bootstrap_source_count <= len(FULL_CHRONOLOGICAL_SOURCE_NAMES):
        raise RuntimeError(f"M2_GROUP_INVALID_BOOTSTRAP_SOURCE_COUNT:{bootstrap_source_count}")
    output_root.mkdir(parents=True, exist_ok=True)
    db = _init_atlas_db(output_root / "atlas.sqlite3")
    try:
        consumed = _consumed(db)
        _assert_prefix(consumed)
        for source, order, stored_digest in consumed:
            loaded = _load_pass_checkpoint(semantic_root, source, software_revision)
            if loaded is None:
                raise RuntimeError(f"M2_GROUP_CONSUMED_SOURCE_NO_LONGER_PASS:{source}")
            _, _, actual_digest = loaded
            if actual_digest != stored_digest:
                raise RuntimeError(f"M2_GROUP_CONSUMED_SOURCE_DIGEST_DRIFT:{source}")

        start = len(consumed)
        if start < bootstrap_source_count:
            stop = bootstrap_source_count
        else:
            stop = len(FULL_CHRONOLOGICAL_SOURCE_NAMES)
        added: list[str] = []
        for order in range(start, stop):
            source = FULL_CHRONOLOGICAL_SOURCE_NAMES[order]
            loaded = _load_pass_checkpoint(semantic_root, source, software_revision)
            if loaded is None:
                break
            source_dir, cp, cp_digest = loaded
            contribution_dir = output_root / "source-contributions" / _slug(source)
            manifest = _build_contribution(
                source=source,
                source_order=order,
                source_dir=source_dir,
                cp=cp,
                cp_digest=cp_digest,
                contribution_dir=contribution_dir,
            )
            _apply_contribution(
                db,
                source=source,
                source_order=order,
                cp_digest=cp_digest,
                contribution_dir=contribution_dir,
                manifest=manifest,
            )
            added.append(source)
            print(
                f"M2_GROUP_SOURCE_PASS|order={order+1}/{len(FULL_CHRONOLOGICAL_SOURCE_NAMES)}|"
                f"source={source}|ticker_days={manifest['ticker_day_memberships']}|"
                f"journeys={manifest['journey_memberships']}"
            )
        atlas = _export_atlas(db, output_root, software_revision)
        atlas["sources_added_this_run"] = added
        print(
            f"M2_GROUP_ATLAS|status={STATUS}|consumed={atlas['source_count_consumed']}/"
            f"{len(FULL_CHRONOLOGICAL_SOURCE_NAMES)}|latest={atlas['latest_consumed_source']}|"
            f"added={len(added)}|formula_stage={FORMULA_STAGE}"
        )
        return atlas
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--software-revision", required=True)
    parser.add_argument("--bootstrap-source-count", type=int, default=8)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.poll_seconds < 60:
        raise RuntimeError("M2_GROUP_WATCH_FREQUENCY_TOO_HIGH")

    last_count = -1
    while True:
        atlas = run_once(
            semantic_root=args.semantic_root,
            output_root=args.output_root,
            software_revision=args.software_revision,
            bootstrap_source_count=args.bootstrap_source_count,
        )
        count = int(atlas["source_count_consumed"])
        if count == len(FULL_CHRONOLOGICAL_SOURCE_NAMES):
            print("M2_GROUP_FULL_SOURCE_CONSUMPTION_PASS")
            return
        if not args.watch:
            return
        if count != last_count:
            next_source = FULL_CHRONOLOGICAL_SOURCE_NAMES[count]
            print(f"M2_GROUP_WATCH|consumed={count}/18|waiting_for_durable_pass={next_source}")
            last_count = count
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
