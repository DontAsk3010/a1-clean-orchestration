from __future__ import annotations

from a1clean.formula_research.m2_full_depth_extension_v2 import augment_scientific_object


def _obj() -> dict:
    return {
        "source_ref": {
            "source_name": "Raw Des 02-31-2024.csv",
            "source_drive_id": "drive-id",
            "source_sha256": "sha",
            "generation_id": "gen",
            "packet_fingerprint": "packet",
        },
        "ticker": "AALI",
        "trading_date": "2024-12-02",
        "source_observation_count": 3,
        "source_phase_counts": {"PREOPEN": 1, "REGULAR_SESSION1": 2},
        "availability_registry": {
            "market_sector_relative_context": "UNKNOWN_UNPROVEN",
            "corporate_action_identity_context": "UNKNOWN_UNPROVEN",
            "exchange_mechanics_context": "PARTIAL_SOURCE_PHASE_AVAILABLE_OTHER_MECHANICS_UNPROVEN",
        },
        "continuous_current_enrichment": {
            "derived_observations": [
                {
                    "source_row": 10,
                    "timestamp": "2024-12-02 08:59:00",
                    "price_geometry": {"close": 99},
                    "lead_lag_observation": {"price": "UNKNOWN", "volume": "UNKNOWN", "value": "UNKNOWN", "nbss": "UNKNOWN", "range": "UNKNOWN"},
                    "causal_timing": {"known_at_status": "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS"},
                },
                {
                    "source_row": 11,
                    "timestamp": "2024-12-02 09:00:00",
                    "price_geometry": {"close": 100},
                    "lead_lag_observation": {"price": "UP", "volume": "UP", "value": "UP", "nbss": "FLAT", "range": "UP"},
                    "causal_timing": {"known_at_status": "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS"},
                },
                {
                    "source_row": 12,
                    "timestamp": "2024-12-02 09:01:00",
                    "price_geometry": {"close": 101},
                    "lead_lag_observation": {"price": "UP", "volume": "DOWN", "value": "DOWN", "nbss": "UP", "range": "FLAT"},
                    "causal_timing": {"known_at_status": "UNKNOWN_UNPROVEN_BAR_TIMESTAMP_COMPLETION_SEMANTICS"},
                },
            ],
            "attempt_topology": {"fresh_high_attempts": 1, "fresh_low_attempts": 0, "open_relation_cross_attempts": 0},
        },
        # Run indices are REGULAR-stream indices, deliberately not full-envelope indices.
        "state_runs": [
            {
                "state_key": "S1",
                "state": {"price_direction": "UP"},
                "start_index": 0,
                "end_index": 1,
                "start_timestamp": "2024-12-02 09:00:00",
                "end_timestamp": "2024-12-02 09:01:00",
                "row_count": 2,
            }
        ],
        "event_journeys": [
            {
                "journey_kind": "RECOVERY",
                "causal_start": {"index": 0, "timestamp": "2024-12-02 09:00:00"},
                "hindsight_resolution": {"resolution_timestamp": "2024-12-02 09:01:00", "resolution_index": 1, "right_censored": False},
            }
        ],
        "behavior_lifecycle": [
            {
                "journey_id": "j1",
                "journey_ordinal": 1,
                "formation_sequence": [],
                "timing": {"event_start_time": "2024-12-02 09:00:00"},
            }
        ],
        "ticker_day_semantic_profile": {"no_forced_event": False},
    }


def test_full_depth_extension_resolves_source_parent_by_timestamp_not_regular_index():
    out = augment_scientific_object(_obj())
    run = out["state_runs"][0]
    assert run["source_parents"]["source_row_first"] == 11
    assert run["source_parents"]["source_row_last"] == 12
    assert run["source_parents"]["resolved_by"] == "EXACT_TIMESTAMP_IN_FULL_ENVELOPE"
    journey = out["event_journeys"][0]
    assert journey["source_parents"]["source_row_first"] == 11
    assert journey["source_parents"]["source_row_last"] == 12


def test_full_depth_formation_snapshot_uses_full_envelope_timestamp_alignment():
    out = augment_scientific_object(_obj())
    snap = out["formation_snapshots_owner_full_depth"][0]
    assert snap["full_envelope_index"] == 1
    assert snap["available_actual_source_rows_through_formation"] == 2
    assert snap["primitive_and_continuous_derived_at_formation"]["source_row"] == 11
    assert snap["hindsight_resolution_separate"]["resolution_timestamp"] == "2024-12-02 09:01:00"


def test_full_depth_extension_adds_required_objective_domains_without_formula():
    out = augment_scientific_object(_obj())
    assert out["owner_full_depth_definition_version"].endswith("_V2")
    assert out["attempt_retest_loop_topology"]["test_retest_candidates_are_objective_revisits_not_automatic_semantic_labels"] is True
    assert out["lead_lag_relationship_graph"]["observed_order_is_not_causation"] is True
    assert out["data_quality_full_depth_audit"]["quality_is_not_market_behavior"] is True
    assert out["owner_full_depth_contract"]["formula_stage"] == "CLOSED"
