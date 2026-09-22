from datetime import datetime, timezone

from a1clean.machine1_monitor import _select_latest, build_snapshot, parse_registry_states


def test_registry_merges_append_only_updates():
    text = """MACHINE-1 DATE CLAIM — x
DATE=2024-12-04
WORKER_ID=W04
COMPLETED_TICKER_CONTEXT_PATHS=10
MACHINE-1 CHECKPOINT — y
DATE=2024-12-04
COMPLETED_TICKER_CONTEXT_PATHS=12
LAST_VERIFIED_TICKER=BBBB
"""
    state = parse_registry_states(text)["2024-12-04"]
    assert state["WORKER_ID"] == "W04"
    assert state["COMPLETED_TICKER_CONTEXT_PATHS"] == "12"
    assert state["LAST_VERIFIED_TICKER"] == "BBBB"


def test_snapshot_prefers_highest_durable_progress_and_latest_heartbeat():
    items = [
        {"id": "cur", "name": "DES2024_20241203__CHECKPOINT_CURRENT.json", "modifiedTime": "2026-09-22T10:00:00Z"},
        {"id": "a12", "name": "DES2024_20241203__CHECKPOINT_ATOMIC_PASS012_TEST__20260922.json", "modifiedTime": "2026-09-22T10:05:00Z"},
    ]
    payloads = {
        "cur": {"source": {"trading_date": "2024-12-03"}, "status": "DATE_OPEN_IN_PROGRESS", "date_scope": {"completed_ticker_context_paths": 10, "total_ticker_context_paths": 891, "completed": ["AAAA"]}, "next_exact_resume_point": {"ticker": "BBBB"}, "consistency_test": {"atomic_checkpoint_state": "ATOMIC_PASS010"}},
        "a12": {"checkpoint": "PASS012_DATE03", "trading_date": "2024-12-03", "worker_id": "W03", "completed_ticker_context_paths": 12, "total_ticker_context_paths": 891, "last_verified_ticker": "CCCC", "next_exact_resume": {"ticker": "DDDD"}, "evidence": {"mode": "GITHUB_SELF_HOSTED_EXACT_RAW_EXTRACTION_ROWS_FILE", "github_run_id": 123}, "atomic_artifact_readback": "PASS"},
    }
    snap = build_snapshot(items, payloads, {"2024-12-03": {"DATE": "2024-12-03", "WORKER_ID": "W03", "COMPLETED_TICKER_CONTEXT_PATHS": "11"}}, now=datetime(2026, 9, 22, 10, 10, tzinfo=timezone.utc))
    row = snap["workers"][0]
    assert (row["completed_ticker_context_paths"], row["last_verified_ticker"], row["next_ticker"]) == (12, "CCCC", "DDDD")
    assert (row["pull_status"], row["health"], row["heartbeat_age_minutes"]) == ("OK", "RECENT_WRITE", 5)


def test_select_latest_does_not_reread_atomic_history():
    items = [
        {"id": "cur2", "name": "DES2024_20241202__CHECKPOINT_CURRENT.json", "modifiedTime": "2026-09-22T10:00:00Z"},
        {"id": "old4", "name": "DES2024_20241204__CHECKPOINT_ATOMIC_PASS164_BSML__20260922.json", "modifiedTime": "2026-09-22T10:01:00Z"},
        {"id": "new4", "name": "DES2024_20241204__CHECKPOINT_ATOMIC_PASS165_BSSR__20260922.json", "modifiedTime": "2026-09-22T10:02:00Z"},
    ]
    assert {row["id"] for row in _select_latest(items)} == {"cur2", "new4"}
