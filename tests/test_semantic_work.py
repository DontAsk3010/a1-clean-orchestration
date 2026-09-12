from __future__ import annotations

from a1clean.config import FROZEN_GENERATION_ID
from a1clean.semantic_work import build_semantic_controls


def _source():
    return {
        "source_drive_id": "src-1",
        "source_name": "Raw Des 02-31-2024.csv",
        "source_sha256": "a" * 64,
        "delta_action": "VERIFIED_UNCHANGED",
        "first_observed_date": "2024-12-02",
        "first_observed_time": "09:00:00",
        "last_observed_date": "2024-12-31",
        "last_observed_time": "16:00:00",
    }


def _classification(data_state="VERIFIED_UNCHANGED"):
    row = {
        "source_drive_id": "src-1",
        "source_name": "Raw Des 02-31-2024.csv",
        "source_sha256": "a" * 64,
    }
    result = {
        "verified_unchanged": [],
        "new_processed": [],
        "changed_rebuilt": [],
        "replacement_same_content": [],
        "removed_purged": [],
        "holds": [],
        "active_source_count": 1,
    }
    mapping = {
        "VERIFIED_UNCHANGED": "verified_unchanged",
        "NEW": "new_processed",
        "CHANGED": "changed_rebuilt",
        "REPLACEMENT_SAME_CONTENT": "replacement_same_content",
    }
    result[mapping[data_state]] = [row]
    return result


def _runtime(state="IN_PROGRESS", sha="a" * 64):
    return {
        "status": "AVAILABLE",
        "holds": [],
        "fingerprint": "runtime",
        "prior_ledger": None,
        "checkpoint_snapshots": [
            {
                "checkpoint_id": "CP",
                "checkpoint_file_id": "file-1",
                "checkpoint_file_name": "DES2024_20241202__CHECKPOINT_CURRENT.json",
                "checkpoint_modified_time": "2026-09-12T13:30:42.451Z",
                "source_drive_id": "src-1",
                "source_name": "Raw Des 02-31-2024.csv",
                "source_sha256": sha,
                "semantic_generation_id": FROZEN_GENERATION_ID,
                "source_mode": "HISTORICAL_REPLAY",
                "semantic_state": state,
                "checkpoint_status": "DATE_OPEN_IN_PROGRESS",
                "current_trading_date": "2024-12-02",
                "total_ticker_context_paths": 892,
                "completed_ticker_context_paths": 123,
                "remaining_ticker_context_paths": 769,
                "next_exact_resume_point": {"ticker": "BIPP", "bundle_line_number": 124},
                "open_carry_count": 86,
                "cross_ticker_reconciliation_state": "PENDING",
            }
        ],
    }


def _build(classification=None, runtime=None):
    return build_semantic_controls(
        active_sources=[_source()],
        classification=classification or _classification(),
        semantic_delta_queue={"queue_role": "DATA_CHANGE_TRIGGER_ONLY"},
        semantic_runtime=runtime if runtime is not None else _runtime(),
        updated_at_utc="2026-09-12T16:00:00+00:00",
    )


def test_verified_unchanged_in_progress_still_resumes_semantic_work():
    bundle = _build()
    queue = bundle["AI_SEMANTIC_WORK_QUEUE.json"]
    ledger = bundle["PERSISTENT_SEMANTIC_RESEARCH_STATE.json"]
    assert queue["work_item_count"] == 1
    assert queue["work_items"][0]["work_kind"] == "RESUME_EXACT_SEMANTIC_CHECKPOINT"
    assert queue["work_items"][0]["next_exact_resume_point"]["ticker"] == "BIPP"
    assert ledger["sources"]["src-1"]["data_state"] == "VERIFIED_UNCHANGED"
    assert ledger["sources"]["src-1"]["semantic_state"] == "IN_PROGRESS"
    assert ledger["watermarks"]["backlog_state"] == "BACKLOGGED"


def test_verified_unchanged_complete_does_not_full_reread():
    bundle = _build(runtime=_runtime(state="COMPLETE"))
    queue = bundle["AI_SEMANTIC_WORK_QUEUE.json"]
    assert queue["work_item_count"] == 0
    assert queue["scheduler_status"] == "NO_PENDING_SEMANTIC_WORK_FOR_DISCOVERED_SCOPE"


def test_changed_source_marks_semantic_state_stale_without_erasing_provenance():
    bundle = _build(classification=_classification("CHANGED"))
    state = bundle["PERSISTENT_SEMANTIC_RESEARCH_STATE.json"]["sources"]["src-1"]
    item = bundle["AI_SEMANTIC_WORK_QUEUE.json"]["work_items"][0]
    assert state["semantic_state"] == "STALE_REQUIRES_REVALIDATION"
    assert state["prior_causal_provenance_preserved"] is True
    assert item["work_kind"] == "SCOPED_REVALIDATION_OR_REREAD"


def test_unknown_semantic_completion_is_never_assumed_complete():
    runtime = {
        "status": "AVAILABLE",
        "holds": [],
        "fingerprint": "runtime",
        "prior_ledger": None,
        "checkpoint_snapshots": [],
    }
    bundle = _build(runtime=runtime)
    item = bundle["AI_SEMANTIC_WORK_QUEUE.json"]["work_items"][0]
    assert item["work_kind"] == "RECONCILE_SEMANTIC_STATE_BEFORE_READING"


def test_live_architecture_keeps_semantic_ai_out_of_latency_critical_loop():
    bundle = _build()
    queue = bundle["AI_SEMANTIC_WORK_QUEUE.json"]
    ledger = bundle["PERSISTENT_SEMANTIC_RESEARCH_STATE.json"]
    assert queue["realtime_readiness"]["semantic_ai_in_latency_critical_signal_loop"] is False
    assert ledger["semantic_reader_is_not_latency_critical_production_signal_loop"] is True
