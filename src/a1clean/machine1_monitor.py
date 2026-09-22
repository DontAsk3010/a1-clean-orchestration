from __future__ import annotations

import argparse
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import BEHAVIOR_CONTROL_FOLDER_DRIVE_ID
from .google_drive import build_drive_api

REGISTRY_ID = "1hI1HAksSGktmjL0sqB1SUhGDaS7NQILHdBoSnE2vR7Q"
CURRENT_RE = re.compile(r"^DES2024_(\d{8})__CHECKPOINT_CURRENT\.json$")
ATOMIC_RE = re.compile(r"^DES2024_(\d{8})__CHECKPOINT_ATOMIC_PASS(\d+)(?:_.*)?\.json$")
KV_RE = re.compile(r"^([A-Z][A-Z0-9_\-]*)=(.*)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UTC_MIN = datetime.min.replace(tzinfo=timezone.utc)


def _dt(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _date(raw):
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _count(value):
    if isinstance(value, int):
        return value, None
    text = str(value or "").strip()
    if text.isdigit():
        return int(text), None
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _ticker(value):
    if isinstance(value, dict):
        return value.get("ticker")
    return str(value).split("|", 1)[0].strip() if value else None


def _list_children(api):
    out, token = [], None
    while True:
        res = api.files().list(
            q=f"'{BEHAVIOR_CONTROL_FOLDER_DRIVE_ID}' in parents and trashed=false",
            fields="nextPageToken,files(id,name,modifiedTime)",
            pageSize=1000, pageToken=token, orderBy="name",
        ).execute()
        out.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            return out


def _download_json(api, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, api.files().get_media(fileId=file_id, supportsAllDrives=True), chunksize=1024 * 1024)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return json.loads(buf.getvalue().decode("utf-8-sig"))


def _select_latest(items):
    """CURRENT plus highest immutable ATOMIC_PASS per trading date."""
    current, atomic = [], {}
    for item in items:
        name = str(item.get("name") or "")
        if CURRENT_RE.match(name):
            current.append(item)
            continue
        m = ATOMIC_RE.match(name)
        if not m:
            continue
        key = _date(m.group(1))
        candidate = (int(m.group(2)), _dt(item.get("modifiedTime")) or UTC_MIN, item)
        if key not in atomic or candidate[:2] > atomic[key][:2]:
            atomic[key] = candidate
    return current + [v[2] for _, v in sorted(atomic.items())]


def parse_registry_states(text):
    states, block = {}, {}

    def flush():
        nonlocal block
        date = block.get("DATE")
        if date and DATE_RE.fullmatch(date):
            merged = states.setdefault(date, {})
            merged.update({k: v for k, v in block.items() if v != ""})
        block = {}

    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if line.startswith("MACHINE-1 ") or line == "CURRENT MACHINE-1 REGISTER":
            flush()
            continue
        m = KV_RE.match(line)
        if m:
            block[m.group(1)] = m.group(2).strip()
    flush()
    return states


def _checkpoint(payload, meta, kind):
    scope = payload.get("date_scope") if isinstance(payload.get("date_scope"), dict) else {}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    consistency = payload.get("consistency_test") if isinstance(payload.get("consistency_test"), dict) else {}
    completed, fraction_total = _count(payload.get("completed_ticker_context_paths", scope.get("completed_ticker_context_paths")))
    total = payload.get("total_ticker_context_paths", scope.get("total_ticker_context_paths"))
    try:
        total = int(total) if total is not None else fraction_total
    except (TypeError, ValueError):
        total = fraction_total
    done = scope.get("completed") if isinstance(scope.get("completed"), list) else []
    nxt = payload.get("next_exact_resume", payload.get("next_exact_resume_point"))
    evidence = payload.get("evidence_access") or payload.get("evidence") or {}
    evidence = evidence if isinstance(evidence, dict) else {}
    readback = payload.get("atomic_artifact_readback") or payload.get("readback_status")
    if readback is None and kind == "CURRENT":
        readback = "CURRENT_DURABLE"
    return {
        "kind": kind,
        "worker_id": payload.get("worker_id"),
        "state": payload.get("state") or payload.get("status") or payload.get("date_status"),
        "date_local_pass": payload.get("date_local_pass"),
        "checkpoint": payload.get("checkpoint") or consistency.get("atomic_checkpoint_state") or payload.get("checkpoint_id"),
        "completed": completed, "total": total,
        "last": payload.get("last_verified_ticker") or (done[-1] if done else None),
        "next": _ticker(nxt), "next_exact": nxt,
        "rows": payload.get("actual_source_rows_read", scope.get("actual_source_rows_read_in_completed_ticker_days")),
        "readback": readback, "pull_mode": evidence.get("mode"),
        "github_run_id": evidence.get("github_run_id"), "github_artifact_id": evidence.get("github_artifact_id"),
        "modified": meta.get("modifiedTime"), "file": meta.get("name"),
    }


def _registry(date, row):
    completed, fraction_total = _count(row.get("COMPLETED_TICKER_CONTEXT_PATHS"))
    total = row.get("TOTAL_TICKER_CONTEXT_PATHS")
    try:
        total = int(total) if total is not None else fraction_total
    except (TypeError, ValueError):
        total = fraction_total
    return {
        "kind": "REGISTRY", "worker_id": row.get("WORKER_ID"),
        "state": row.get("STATE") or row.get("DATE_STATUS"), "date_local_pass": row.get("DATE_LOCAL_PASS"),
        "checkpoint": row.get("CHECKPOINT") or row.get("CHECKPOINT_POINTER"),
        "completed": completed, "total": total, "last": row.get("LAST_VERIFIED_TICKER"),
        "next": _ticker(row.get("NEXT_EXACT_RESUME")), "next_exact": row.get("NEXT_EXACT_RESUME"),
        "rows": row.get("ACTUAL_SOURCE_ROWS_READ"), "readback": row.get("READBACK_STATUS"),
        "handoff": row.get("HANDOFF_TICKET"), "assignment": row.get("ASSIGNMENT"),
    }


def _health(modified, now):
    stamp = _dt(modified)
    if not stamp:
        return "NO_FILE_HEARTBEAT", None
    age = max(0, int((now - stamp).total_seconds() // 60))
    return ("RECENT_WRITE" if age <= 20 else "QUIET_NO_RECENT_WRITE" if age <= 90 else "STALE_OBSERVATION_ONLY"), age


def build_snapshot(items, payloads, registry, now=None):
    now = now or datetime.now(timezone.utc)
    files = {}
    for meta in items:
        name = str(meta.get("name") or "")
        m, kind, pnum = CURRENT_RE.match(name), "CURRENT", -1
        if not m:
            m, kind = ATOMIC_RE.match(name), "ATOMIC"
            pnum = int(m.group(2)) if m else -1
        if not m or meta.get("id") not in payloads:
            continue
        date = _date(m.group(1))
        row = _checkpoint(payloads[meta["id"]], meta, kind)
        row["pass_number"] = pnum
        files.setdefault(date, []).append(row)

    workers = []
    for date in sorted(set(files) | set(registry)):
        rows = files.get(date, [])
        current = max((r for r in rows if r["kind"] == "CURRENT"), key=lambda r: _dt(r["modified"]) or UTC_MIN, default=None)
        atomic = max((r for r in rows if r["kind"] == "ATOMIC"), key=lambda r: (r["pass_number"], _dt(r["modified"]) or UTC_MIN), default=None)
        reg = _registry(date, registry[date]) if date in registry else None
        candidates = [r for r in (current, atomic, reg) if r]
        best = max((r for r in candidates if r.get("completed") is not None), key=lambda r: (r["completed"], _dt(r.get("modified")) or UTC_MIN), default=current or atomic or reg or {})
        heartbeat = max((r for r in (current, atomic) if r), key=lambda r: _dt(r["modified"]) or UTC_MIN, default=None)
        health, age = _health(heartbeat.get("modified") if heartbeat else None, now)
        worker_id = next((r.get("worker_id") for r in (reg, atomic, current) if r and r.get("worker_id")), "UNKNOWN_FROM_CHECKPOINT")
        total, completed = best.get("total"), best.get("completed")
        pull = atomic if atomic and atomic.get("pull_mode") else current
        readback = best.get("readback") or next((r.get("readback") for r in candidates if r.get("readback")), None) or "UNKNOWN"
        workers.append({
            "trading_date": date, "worker_id": worker_id, "state": best.get("state") or "UNKNOWN",
            "date_local_pass": best.get("date_local_pass") or "UNKNOWN", "checkpoint_source": best.get("kind"),
            "checkpoint": best.get("checkpoint"), "completed_ticker_context_paths": completed,
            "total_ticker_context_paths": total, "remaining_ticker_context_paths": total - completed if total is not None and completed is not None else None,
            "progress_pct": round(100 * completed / total, 2) if total and completed is not None else None,
            "last_verified_ticker": best.get("last"), "next_ticker": best.get("next"), "next_exact_resume": best.get("next_exact"),
            "actual_source_rows_read": best.get("rows"), "pull_status": "OK" if pull and pull.get("pull_mode") else "NOT_EXPOSED_IN_SELECTED_CHECKPOINT",
            "pull_mode": pull.get("pull_mode") if pull else None, "github_run_id": pull.get("github_run_id") if pull else None,
            "github_artifact_id": pull.get("github_artifact_id") if pull else None,
            "store_status": "CHECKPOINT_WRITTEN_READBACK_PENDING" if str(readback).upper() == "PENDING" else "OK" if heartbeat else "NO_DURABLE_CHECKPOINT_FOUND",
            "readback_status": readback, "heartbeat_file": heartbeat.get("file") if heartbeat else None,
            "heartbeat_time_utc": heartbeat.get("modified") if heartbeat else None, "heartbeat_age_minutes": age, "health": health,
            "handoff_ticket": reg.get("handoff") if reg else None, "assignment": reg.get("assignment") if reg else None,
            "official_current": current, "latest_atomic": atomic,
        })
    return {"schema": "A1_MACHINE1_MULTIWORKER_OBSERVABILITY_V1", "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
            "role": "READ_ONLY_OBSERVABILITY_NO_ANALYTICAL_AUTHORITY", "worker_count": len(workers), "workers": workers,
            "recent_write_count": sum(w["health"] == "RECENT_WRITE" for w in workers),
            "quiet_count": sum(w["health"] == "QUIET_NO_RECENT_WRITE" for w in workers),
            "stale_observation_count": sum(w["health"] == "STALE_OBSERVATION_ONLY" for w in workers),
            "safety": {"raw_write": False, "current_write": False, "registry_write": False, "semantic_interpretation": False, "formula_or_signal_logic": False}}


def _render(snapshot):
    lines = ["# A1 CLEAN — MACHINE 1 LIVE MONITOR", "", f"Generated: {snapshot['generated_at_utc']}",
             f"Monitor status: {snapshot.get('monitor_status', 'UNKNOWN')}", "",
             "| Date | Worker | Health | Progress | Last | Next | Pull | Store / Readback | Age |", "|---|---|---|---|---|---|---|---|---|"]
    for w in snapshot["workers"]:
        progress = f"{w['completed_ticker_context_paths']}/{w['total_ticker_context_paths']} ({w['progress_pct']}%)"
        lines.append(f"| {w['trading_date']} | {w['worker_id']} | {w['health']} | {progress} | {w['last_verified_ticker']} | {w['next_ticker']} | {w['pull_status']} | {w['store_status']} / {w['readback_status']} | {w['heartbeat_age_minutes']} min |")
        lines += ["", f"{w['trading_date']} next exact resume: {w['next_exact_resume']}", ""]
    lines += ["> Read-only observability only. No RAW/CURRENT/registry/semantic write and no formula/signal logic."]
    return "\n".join(lines)


def collect_snapshot():
    api = build_drive_api(read_write=False)
    items = _select_latest(_list_children(api))
    payloads, holds = {}, []
    for item in items:
        try:
            payloads[item["id"]] = _download_json(api, item["id"])
        except Exception as exc:
            holds.append({"file": item.get("name"), "error": f"{type(exc).__name__}: {exc}"})
    registry_error = None
    try:
        raw = api.files().export_media(fileId=REGISTRY_ID, mimeType="text/plain").execute()
        registry = parse_registry_states(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except Exception as exc:
        registry, registry_error = {}, f"{type(exc).__name__}: {exc}"
    snapshot = build_snapshot(items, payloads, registry)
    snapshot.update({"artifact_read_holds": holds, "registry_read_error": registry_error,
                     "monitor_status": "PASS" if not holds and not registry_error else "PARTIAL_READ_HOLD"})
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Read-only Machine 1 multi-worker monitor")
    parser.add_argument("--output-dir", required=True)
    out = Path(parser.parse_args().output_dir)
    out.mkdir(parents=True, exist_ok=True)
    snapshot = collect_snapshot()
    (out / "machine1-monitor-latest.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "machine1-monitor-latest.md").write_text(_render(snapshot) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
