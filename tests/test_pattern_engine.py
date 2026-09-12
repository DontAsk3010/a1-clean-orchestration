from __future__ import annotations

from a1clean.pattern_discovery.contracts import DiscoveryPlan
from a1clean.pattern_discovery.engine import run_discovery_plan
from a1clean.pattern_discovery.packet import parse_semantic_packet


def _packet():
    return parse_semantic_packet(
        {
            "generation_id": "GEN",
            "source_drive_id": "SRCID",
            "source_name": "Raw X.csv",
            "source_sha256": "abc",
            "trading_date": "2025-01-02",
            "ticker": "AAAA",
            "first_clock_time": "09:00:00",
            "last_clock_time": "09:05:00",
            "data_row_count": 6,
            "source_row_first": 10,
            "source_row_last": 15,
            "source_row_segments": [[10, 15]],
            "raw_header": "RAW_TICKER,RAW_DATETIME_ISO,RAW_CLOSE,RAW_VOLUME",
            "raw_rows": [
                "AAAA,2025-01-02 09:00:00,100,10",
                "AAAA,2025-01-02 09:01:00,101,20",
                "AAAA,2025-01-02 09:02:00,102,30",
                "AAAA,2025-01-02 09:03:00,103,40",
                "AAAA,2025-01-02 09:04:00,104,50",
                "AAAA,2025-01-02 09:05:00,105,60",
            ],
            "all_source_columns_retained": True,
        }
    )


def _sparse_packet():
    return parse_semantic_packet(
        {
            "generation_id": "GEN",
            "source_drive_id": "SRCID",
            "source_name": "Raw X.csv",
            "source_sha256": "abc",
            "trading_date": "2025-01-02",
            "ticker": "THIN",
            "first_clock_time": "09:00:00",
            "last_clock_time": "09:00:00",
            "data_row_count": 1,
            "source_row_first": 100,
            "source_row_last": 100,
            "source_row_segments": [[100, 100]],
            "raw_header": "RAW_TICKER,RAW_DATETIME_ISO,RAW_CLOSE,RAW_VOLUME",
            "raw_rows": ["THIN,2025-01-02 09:00:00,100,10"],
            "all_source_columns_retained": True,
        }
    )


def test_engine_maps_algorithmic_evidence_back_to_source_without_ai_labels(monkeypatch):
    import a1clean.pattern_discovery.engine as engine

    monkeypatch.setattr(engine, "segment", lambda *a, **k: [2, 6])
    monkeypatch.setattr(
        engine,
        "matrix_profile",
        lambda *a, **k: [
            [1.0, 2, -1, 2],
            [2.0, 3, -1, 3],
            [1.0, 0, 0, -1],
            [2.0, 1, 1, -1],
        ],
    )
    monkeypatch.setattr(engine, "dtw_distance", lambda *a, **k: 7.5)

    plan = DiscoveryPlan.from_dict(
        {
            "plan_id": "explicit",
            "ruptures": [
                {
                    "run_id": "cp",
                    "field": "RAW_CLOSE",
                    "algorithm": "Pelt",
                    "model": "l2",
                    "predict_kwargs": {"pen": 1.0},
                }
            ],
            "stumpy": [{"run_id": "mp", "field": "RAW_CLOSE", "window": 3}],
            "dtw": [{"run_id": "dtw", "left_field": "RAW_CLOSE", "right_field": "RAW_VOLUME"}],
        }
    )
    result = run_discovery_plan(_packet(), plan)
    assert result["independence_assertions"]["ai_semantic_labels_consumed"] is False
    assert result["independence_assertions"]["outcomes_consumed"] is False
    assert result["independence_assertions"]["trading_signal_created"] is False
    assert result["runs"][0]["status"] == "EXECUTED"
    assert result["runs"][0]["segments"][0]["source_range"]["start"]["source_row"] == 10
    assert result["runs"][0]["segments"][0]["source_range"]["end"]["source_row"] == 11
    assert result["runs"][1]["status"] == "EXECUTED"
    assert result["runs"][1]["profile_rows"][0]["nearest_neighbor_range"]["start"]["source_row"] == 12
    assert result["runs"][2]["scope"] == "WITHIN_PACKET_ONLY_NOT_CROSS_TICKER_CLUSTERING"
    assert result["run_status_counts"] == {"EXECUTED": 3}


def test_sparse_ticker_day_is_retained_as_not_applicable_evidence(monkeypatch):
    import a1clean.pattern_discovery.engine as engine

    def should_not_execute(*args, **kwargs):
        raise AssertionError("algorithm must not execute when its minimum row contract is unmet")

    monkeypatch.setattr(engine, "segment", should_not_execute)
    monkeypatch.setattr(engine, "matrix_profile", should_not_execute)

    plan = DiscoveryPlan.from_dict(
        {
            "plan_id": "sparse-controls",
            "ruptures": [
                {
                    "run_id": "cp",
                    "field": "RAW_CLOSE",
                    "algorithm": "Pelt",
                    "model": "l2",
                    "predict_kwargs": {"pen": 1.0},
                }
            ],
            "stumpy": [{"run_id": "mp", "field": "RAW_CLOSE", "window": 3}],
            "dtw": [],
        }
    )

    result = run_discovery_plan(_sparse_packet(), plan)
    assert result["packet_identity"]["ticker"] == "THIN"
    assert result["run_status_counts"] == {"NOT_APPLICABLE_INSUFFICIENT_ROWS": 2}
    assert result["runs"][0]["actual_rows"] == 1
    assert result["runs"][0]["required_minimum_rows"] == 2
    assert result["runs"][1]["actual_rows"] == 1
    assert result["runs"][1]["required_minimum_rows"] == 6
    assert result["independence_assertions"]["sampling_used"] is False
