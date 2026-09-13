from a1clean.pattern_discovery.intake import (
    FULL_BACKLOG_POLICY,
    INTAKE_SCHEMA,
    INTAKE_STATUS_COMPLETE,
    INTAKE_STATUS_WORK_PENDING,
    PREEXISTING_COMPLETE,
    SOURCE_COMPLETE,
    SOURCE_QUEUED_CHANGED,
    SOURCE_QUEUED_EXISTING,
    SOURCE_QUEUED_NEW,
    SOURCE_REMOVED,
    classify_current_universe,
    initialize_baseline_state,
    order_source_queue,
)


class DummyPlan:
    plan_id = "L2_CORPUS_STRUCTURAL_STAGE1_UNINTERPRETED_V1"
    sha256 = "plan-fingerprint"


def ident(name: str, sha: str, drive: str = "drive", generation: str = "gen"):
    return {
        "source_name": name,
        "source_drive_id": drive,
        "source_sha256": sha,
        "generation_id": generation,
        "data_plane_manifest_file_id": f"manifest-{name}",
        "data_plane_manifest_modified_time": "2026-09-13T00:00:00Z",
    }


def test_first_activation_queues_all_existing_incomplete_sources():
    ready = [ident("Raw A.csv", "aaa"), ident("Raw B.csv", "bbb")]
    state = initialize_baseline_state(
        ready_sources=ready,
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    assert state["schema"] == INTAKE_SCHEMA
    assert state["status"] == INTAKE_STATUS_WORK_PENDING
    assert state["baseline_policy"] == FULL_BACKLOG_POLICY
    assert state["pending_sources"] == ["Raw A.csv", "Raw B.csv"]
    assert state["sources"]["Raw A.csv"]["status"] == SOURCE_QUEUED_EXISTING
    assert state["sources"]["Raw B.csv"]["status"] == SOURCE_QUEUED_EXISTING


def test_preexisting_complete_is_preserved_and_not_queued():
    ready = [ident("Raw Des.csv", "dec")]
    completion = {
        "Raw Des.csv": {
            "source_identity": {
                "source_name": "Raw Des.csv",
                "source_drive_id": "drive",
                "source_sha256": "dec",
                "generation_id": "gen",
            },
            "last_completed_date": "2024-12-30",
        }
    }
    state = initialize_baseline_state(
        ready_sources=ready,
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states=completion,
    )
    assert state["status"] == INTAKE_STATUS_COMPLETE
    assert state["pending_sources"] == []
    assert state["sources"]["Raw Des.csv"]["status"] == PREEXISTING_COMPLETE
    assert state["sources"]["Raw Des.csv"]["last_result"]["last_completed_date"] == "2024-12-30"


def test_new_source_after_existing_universe_is_queued():
    state = initialize_baseline_state(
        ready_sources=[ident("Raw A.csv", "aaa")],
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    # Simulate A having completed before B arrives.
    state["sources"]["Raw A.csv"]["status"] = SOURCE_COMPLETE
    state["sources"]["Raw A.csv"]["auto_eligible"] = False
    state["sources"]["Raw A.csv"]["completed_source_identity"] = {"source_name": "Raw A.csv"}
    pending = classify_current_universe(
        state=state,
        ready_sources=[ident("Raw A.csv", "aaa"), ident("Raw B.csv", "bbb")],
        not_ready_sources=[],
    )
    assert pending == ["Raw B.csv"]
    assert state["sources"]["Raw B.csv"]["status"] == SOURCE_QUEUED_NEW


def test_changed_content_is_queued_and_removed_source_is_retained():
    state = initialize_baseline_state(
        ready_sources=[ident("Raw A.csv", "aaa"), ident("Raw B.csv", "bbb")],
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    state["sources"]["Raw A.csv"]["status"] = SOURCE_COMPLETE
    state["sources"]["Raw A.csv"]["completed_source_identity"] = {"source_name": "Raw A.csv"}
    pending = classify_current_universe(
        state=state,
        ready_sources=[ident("Raw A.csv", "aaa-v2")],
        not_ready_sources=[],
    )
    assert pending == ["Raw A.csv"]
    assert state["sources"]["Raw A.csv"]["status"] == SOURCE_QUEUED_CHANGED
    assert state["sources"]["Raw B.csv"]["status"] == SOURCE_REMOVED


def test_legacy_baseline_source_is_migrated_into_required_backlog():
    current = ident("Raw A.csv", "aaa")
    state = initialize_baseline_state(
        ready_sources=[current],
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    state["baseline_policy"] = "CURRENT_READY_UNIVERSE_AT_FIRST_ACTIVATION_IS_BASELINE_NOT_RETROACTIVELY_AUTO_QUEUED"
    state["sources"]["Raw A.csv"]["status"] = "BASELINE_PRESENT_NOT_AUTO_QUEUED"
    state["sources"]["Raw A.csv"]["auto_eligible"] = False
    state["pending_sources"] = []
    pending = classify_current_universe(
        state=state,
        ready_sources=[current],
        not_ready_sources=[],
    )
    assert pending == ["Raw A.csv"]
    assert state["baseline_policy"] == FULL_BACKLOG_POLICY
    assert state["sources"]["Raw A.csv"]["status"] == SOURCE_QUEUED_EXISTING


def test_source_queue_uses_governed_manifest_dates_not_filename_order():
    pending = ["Raw Z.csv", "Raw A.csv", "Raw M.csv"]
    coverage = {
        "Raw Z.csv": {
            "first_trading_date": "2025-01-02",
            "last_trading_date": "2025-01-31",
            "source_drive_id": "z",
        },
        "Raw A.csv": {
            "first_trading_date": "2026-01-02",
            "last_trading_date": "2026-01-30",
            "source_drive_id": "a",
        },
        "Raw M.csv": {
            "first_trading_date": "2025-03-03",
            "last_trading_date": "2025-03-31",
            "source_drive_id": "m",
        },
    }
    assert order_source_queue(pending, coverage) == ["Raw Z.csv", "Raw M.csv", "Raw A.csv"]
