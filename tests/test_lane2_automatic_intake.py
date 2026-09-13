from a1clean.pattern_discovery.intake import (
    BASELINE_SOURCE,
    INTAKE_SCHEMA,
    INTAKE_STATUS_BASELINE,
    PREEXISTING_COMPLETE,
    SOURCE_QUEUED_CHANGED,
    SOURCE_QUEUED_NEW,
    SOURCE_REMOVED,
    classify_current_universe,
    initialize_baseline_state,
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


def test_first_activation_baselines_existing_sources_without_retro_queue():
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
    assert state["status"] == INTAKE_STATUS_BASELINE
    assert state["pending_sources"] == []
    assert state["sources"]["Raw A.csv"]["status"] == BASELINE_SOURCE
    assert state["sources"]["Raw B.csv"]["status"] == BASELINE_SOURCE


def test_preexisting_complete_is_preserved_at_baseline():
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
    assert state["sources"]["Raw Des.csv"]["status"] == PREEXISTING_COMPLETE
    assert state["sources"]["Raw Des.csv"]["last_result"]["last_completed_date"] == "2024-12-30"


def test_new_source_after_baseline_is_queued_once():
    state = initialize_baseline_state(
        ready_sources=[ident("Raw A.csv", "aaa")],
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    pending = classify_current_universe(
        state=state,
        ready_sources=[ident("Raw A.csv", "aaa"), ident("Raw B.csv", "bbb")],
        not_ready_sources=[],
    )
    assert pending == ["Raw B.csv"]
    assert state["sources"]["Raw B.csv"]["status"] == SOURCE_QUEUED_NEW


def test_changed_content_after_baseline_is_queued_and_removed_source_is_retained():
    state = initialize_baseline_state(
        ready_sources=[ident("Raw A.csv", "aaa"), ident("Raw B.csv", "bbb")],
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    pending = classify_current_universe(
        state=state,
        ready_sources=[ident("Raw A.csv", "aaa-v2")],
        not_ready_sources=[],
    )
    assert pending == ["Raw A.csv"]
    assert state["sources"]["Raw A.csv"]["status"] == SOURCE_QUEUED_CHANGED
    assert state["sources"]["Raw B.csv"]["status"] == SOURCE_REMOVED


def test_same_unchanged_baseline_source_does_not_become_pending():
    current = ident("Raw A.csv", "aaa")
    state = initialize_baseline_state(
        ready_sources=[current],
        not_ready_sources=[],
        plan=DummyPlan(),
        packets_per_shard=50,
        software_revision="rev-1",
        completion_states={},
    )
    pending = classify_current_universe(
        state=state,
        ready_sources=[current],
        not_ready_sources=[],
    )
    assert pending == []
    assert state["sources"]["Raw A.csv"]["status"] == BASELINE_SOURCE
