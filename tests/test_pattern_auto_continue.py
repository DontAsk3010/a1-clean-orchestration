from __future__ import annotations

from types import SimpleNamespace

import pytest

from a1clean.pattern_discovery.auto_continue import (
    build_trading_date_scopes,
    next_trading_date_scope,
    validate_complete_pass_checkpoint,
)
from a1clean.pattern_discovery.contracts import LANE_ID, PatternDiscoveryContractError
from a1clean.pattern_discovery.runner import CHECKPOINT_SCHEMA


class _Row:
    def __init__(self, manifest_index: int, trading_date: str, ticker: str, data_row_count: int):
        self.manifest_index = manifest_index
        self.trading_date = trading_date
        self.ticker = ticker
        self.data_row_count = data_row_count


class _Identity:
    def as_dict(self):
        return {
            "source_name": "Raw Des 02-31-2024.csv",
            "source_drive_id": "drive-id",
            "source_sha256": "source-sha",
            "generation_id": "generation",
            "data_plane_manifest_file_id": "data-manifest",
            "semantic_manifest_file_id": "semantic-manifest",
            "semantic_manifest_fingerprint": "semantic-fingerprint",
            "ticker_day_count": 4,
            "source_data_rows": 42,
        }


class _Plan:
    plan_id = "L2_CORPUS_STRUCTURAL_STAGE1_UNINTERPRETED_V1"
    sha256 = "plan-fingerprint"


def _rows():
    return (
        _Row(0, "2024-12-02", "AALI", 10),
        _Row(1, "2024-12-02", "ABBA", 11),
        _Row(2, "2024-12-03", "AALI", 12),
        _Row(3, "2024-12-05", "AALI", 9),
    )


def test_next_date_comes_from_manifest_not_calendar_plus_one():
    scopes = build_trading_date_scopes(_rows())
    assert [scope.trading_date for scope in scopes] == ["2024-12-02", "2024-12-03", "2024-12-05"]
    assert scopes[0].packet_count == 2
    assert scopes[0].source_row_count == 21
    assert next_trading_date_scope(scopes, after_date="2024-12-03").trading_date == "2024-12-05"
    assert next_trading_date_scope(scopes, after_date="2024-12-05") is None


def test_manifest_date_must_be_contiguous_and_strictly_chronological():
    with pytest.raises(PatternDiscoveryContractError, match="DATE_NOT_CONTIGUOUS"):
        build_trading_date_scopes(
            (
                _Row(0, "2024-12-02", "AALI", 1),
                _Row(1, "2024-12-03", "AALI", 1),
                _Row(2, "2024-12-02", "ABBA", 1),
            )
        )
    with pytest.raises(PatternDiscoveryContractError, match="NOT_STRICTLY_CHRONOLOGICAL"):
        build_trading_date_scopes(
            (
                _Row(0, "2024-12-03", "AALI", 1),
                _Row(1, "2024-12-02", "AALI", 1),
            )
        )


def test_anchor_must_exist_exactly_once_in_manifest_date_scopes():
    scopes = build_trading_date_scopes(_rows())
    with pytest.raises(PatternDiscoveryContractError, match="ANCHOR_DATE_CARDINALITY"):
        next_trading_date_scope(scopes, after_date="2024-12-04")


def test_complete_pass_gate_requires_full_packets_rows_and_no_hold():
    reader = SimpleNamespace(identity=_Identity())
    plan = _Plan()
    scope = build_trading_date_scopes(_rows())[1]
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "lane_id": LANE_ID,
        "status": "PASS",
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "scope": {"scope_type": "EXACT_TRADING_DATE", "trading_date": "2024-12-03"},
        "total_manifest_packets": 1,
        "completed_manifest_packets": 1,
        "selected_source_rows": 12,
        "completed_source_rows": 12,
        "hold": None,
        "next_exact_resume_point": None,
        "evidence_manifest": {"id": "evidence"},
        "run_result": {"id": "audit"},
    }
    validate_complete_pass_checkpoint(checkpoint, reader=reader, plan=plan, scope=scope)

    checkpoint["completed_source_rows"] = 11
    with pytest.raises(PatternDiscoveryContractError, match="PASS_GATE_FAILED.*completed_source_rows"):
        validate_complete_pass_checkpoint(checkpoint, reader=reader, plan=plan, scope=scope)


def test_hold_or_partial_checkpoint_cannot_open_next_date():
    reader = SimpleNamespace(identity=_Identity())
    plan = _Plan()
    scope = build_trading_date_scopes(_rows())[1]
    checkpoint = {
        "schema": CHECKPOINT_SCHEMA,
        "lane_id": LANE_ID,
        "status": "HOLD",
        "source_identity": reader.identity.as_dict(),
        "plan_id": plan.plan_id,
        "plan_fingerprint": plan.sha256,
        "scope": {"scope_type": "EXACT_TRADING_DATE", "trading_date": "2024-12-03"},
        "total_manifest_packets": 1,
        "completed_manifest_packets": 1,
        "selected_source_rows": 12,
        "completed_source_rows": 12,
        "hold": {"reason": "observed failure"},
        "next_exact_resume_point": {"manifest_index": 2},
        "evidence_manifest": None,
        "run_result": None,
    }
    with pytest.raises(PatternDiscoveryContractError, match="PASS_GATE_FAILED"):
        validate_complete_pass_checkpoint(checkpoint, reader=reader, plan=plan, scope=scope)
