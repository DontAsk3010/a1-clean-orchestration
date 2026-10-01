from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from a1clean.formula_research import v32_current_scientific_restart as current
from a1clean.formula_research.m2_current_next_date import (
    AUTH_SCHEMA,
    build_rebound_checkpoint,
    resolve_exact_successor,
    validate_next_date_authorization,
)
from a1clean.formula_research.source_universe_manifest import _digest


@dataclass(frozen=True)
class FakeRow:
    manifest_index: int
    trading_date: str
    ticker: str
    data_row_count: int
    source_row_first: int
    source_row_last: int
    first_clock_time: str = "09:00:00"
    last_clock_time: str = "15:49:00"

    def as_dict(self) -> dict:
        return {
            "manifest_index": self.manifest_index,
            "trading_date": self.trading_date,
            "ticker": self.ticker,
            "data_row_count": self.data_row_count,
            "source_row_first": self.source_row_first,
            "source_row_last": self.source_row_last,
            "first_clock_time": self.first_clock_time,
            "last_clock_time": self.last_clock_time,
        }


class FakeIdentity:
    def __init__(self, source_name: str, source_drive_id: str, source_sha256: str):
        self.source_name = source_name
        self.source_drive_id = source_drive_id
        self.source_sha256 = source_sha256

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "source_drive_id": self.source_drive_id,
            "source_sha256": self.source_sha256,
        }


class FakeReader:
    def __init__(self, source_name: str, source_drive_id: str, source_sha256: str, rows: list[FakeRow]):
        self.identity = FakeIdentity(source_name, source_drive_id, source_sha256)
        self.semantic_manifest_rows = rows


def _manifest(source_defs: list[tuple[str, str, str, str, str]]) -> dict:
    rows = []
    for index, (name, drive_id, digest, first_date, last_date) in enumerate(source_defs):
        rows.append(
            {
                "source_name": name,
                "source_drive_id": drive_id,
                "digest_sha256": digest,
                "first_date": first_date,
                "last_date": last_date,
                "eligibility": "ELIGIBLE_GOVERNED_ACTIVE",
                "ready": True,
                "ordering_key": {"index": index},
            }
        )
    out = {
        "status": "PASS",
        "sources": rows,
        "source_names_in_order": [row["source_name"] for row in rows],
        "semantic_date_envelope_reconciliation": {"status": "PASS"},
        "authority_sync": {"status": "PASS", "authority_corpus_sha256": "authority-digest"},
    }
    out["manifest_digest"] = _digest(out)
    return out


def _auth(**updates) -> dict:
    out = {
        "schema": AUTH_SCHEMA,
        "enabled": True,
        "lineage": current.LINEAGE,
        "one_date_per_authorization": True,
        "exact_next_governed_successor_only": True,
        "arbitrary_target_date_forbidden": True,
        "prior_checkpoint_must_be_date_closed": True,
        "fresh_current_prestart_required": True,
        "identity_rebind_only_at_safe_date_boundary": True,
        "carry_forward_required": True,
        "no_auto_advance_after_date_close": True,
        "expected_last_closed_source": "S1",
        "expected_last_closed_date": "2024-12-02",
        "formula_stage": "CLOSED",
        "grouping_stage": "HOLD",
    }
    out.update(updates)
    return out


def _identity() -> dict:
    return {
        "lineage": current.LINEAGE,
        "request_sha256": "request-new",
        "software_revision": "new-head",
        "source_universe_manifest_digest": "manifest-new",
        "authority_corpus_sha256": "authority-new",
        "master_document_id": "master-id",
        "master_revision_id": "master-rev",
        "coverage_matrix_document_id": "matrix-id",
        "coverage_matrix_revision_id": "matrix-rev",
        "old_pass_completion_inherited": False,
        "old_scientific_checkpoint_read_for_completion": False,
    }


def _closed_checkpoint() -> dict:
    return {
        "schema": current.CHECKPOINT_SCHEMA,
        "lineage": current.LINEAGE,
        "request_sha256": "request-old",
        "software_revision": "old-head",
        "source_universe_manifest_digest": "manifest-old",
        "authority_corpus_sha256": "authority-old",
        "master_document_id": "master-id",
        "master_revision_id": "master-rev",
        "coverage_matrix_document_id": "matrix-id",
        "coverage_matrix_revision_id": "matrix-rev",
        "old_pass_completion_inherited": False,
        "old_scientific_checkpoint_read_for_completion": False,
        "status": "DATE_CLOSED",
        "current_source": "S1",
        "current_date": "2024-12-02",
        "last_closed_date": "2024-12-02",
        "completed_units_in_current_date": 2,
        "completed_source_rows_in_current_date": 8,
        "output_shards": [{"id": "shard-1"}, {"id": "shard-2"}],
        "last_completed": {
            "selection_position": 1,
            "manifest_index": 1,
            "trading_date": "2024-12-02",
            "ticker": "BBBB",
            "data_row_count": 4,
            "first_clock_time": "09:00:00",
            "last_clock_time": "15:49:00",
            "source_row_first": 5,
            "source_row_last": 8,
        },
        "next_exact_resume_point": None,
        "date_close": {"id": "close-id", "name": "close.json", "sha256": "close-sha"},
        "carry_by_ticker": {
            "AAAA": {"date": "2024-12-02", "terminal_carry_state": {"x": 1}},
            "BBBB": {"date": "2024-12-02", "terminal_carry_state": {"x": 2}},
        },
        "hold": None,
    }


def test_authorization_forbids_caller_selected_target_date():
    validate_next_date_authorization(_auth())
    with pytest.raises(RuntimeError, match="M2_NEXT_ARBITRARY_TARGET_FIELD_FORBIDDEN"):
        validate_next_date_authorization(_auth(target_date="2024-12-10"))


def test_authorization_must_be_explicitly_enabled_and_one_date_only():
    with pytest.raises(RuntimeError, match="M2_NEXT_AUTH_DISABLED"):
        validate_next_date_authorization(_auth(enabled=False))
    with pytest.raises(RuntimeError, match="M2_NEXT_AUTH_CONTRACT_MISMATCH"):
        validate_next_date_authorization(_auth(one_date_per_authorization=False))


def test_successor_is_exact_next_date_within_same_source():
    manifest = _manifest([("S1", "id1", "sha1", "2024-12-02", "2024-12-04")])
    readers = {
        "S1": FakeReader(
            "S1",
            "id1",
            "sha1",
            [
                FakeRow(0, "2024-12-02", "AAAA", 4, 1, 4),
                FakeRow(1, "2024-12-03", "AAAA", 5, 5, 9),
                FakeRow(2, "2024-12-03", "BBBB", 6, 10, 15),
                FakeRow(3, "2024-12-04", "AAAA", 7, 16, 22),
            ],
        )
    }
    successor = resolve_exact_successor(
        manifest,
        last_source="S1",
        last_date="2024-12-02",
        reader_factory=lambda name: readers[name],
    )
    assert successor is not None
    assert successor["source_name"] == "S1"
    assert successor["trading_date"] == "2024-12-03"
    assert successor["ticker_day_count"] == 2
    assert successor["source_row_count"] == 11
    assert successor["first_unit"]["ticker"] == "AAAA"
    assert successor["first_unit"]["selection_position"] == 0


def test_successor_crosses_source_boundary_without_skipping():
    manifest = _manifest(
        [
            ("S1", "id1", "sha1", "2024-12-02", "2024-12-02"),
            ("S2", "id2", "sha2", "2025-01-02", "2025-01-03"),
        ]
    )
    readers = {
        "S1": FakeReader("S1", "id1", "sha1", [FakeRow(0, "2024-12-02", "AAAA", 4, 1, 4)]),
        "S2": FakeReader(
            "S2",
            "id2",
            "sha2",
            [FakeRow(0, "2025-01-02", "AAAA", 5, 1, 5), FakeRow(1, "2025-01-03", "AAAA", 6, 6, 11)],
        ),
    }
    successor = resolve_exact_successor(
        manifest,
        last_source="S1",
        last_date="2024-12-02",
        reader_factory=lambda name: readers[name],
    )
    assert successor is not None
    assert (successor["source_name"], successor["trading_date"]) == ("S2", "2025-01-02")


def test_final_governed_date_has_no_successor():
    manifest = _manifest([("S1", "id1", "sha1", "2024-12-02", "2024-12-02")])
    reader = FakeReader("S1", "id1", "sha1", [FakeRow(0, "2024-12-02", "AAAA", 4, 1, 4)])
    assert resolve_exact_successor(
        manifest,
        last_source="S1",
        last_date="2024-12-02",
        reader_factory=lambda _: reader,
    ) is None


def test_rebind_only_at_date_closed_preserves_carry_and_resets_date_counters():
    cp = _closed_checkpoint()
    successor = {
        "source_name": "S1",
        "trading_date": "2024-12-03",
        "first_unit": FakeRow(2, "2024-12-03", "AAAA", 5, 9, 13).as_dict() | {"selection_position": 0},
    }
    rebound = build_rebound_checkpoint(
        cp,
        expected_last_source="S1",
        expected_last_date="2024-12-02",
        successor=successor,
        new_identity=_identity(),
        transition_name="transition.json",
    )
    assert rebound["status"] == "IN_PROGRESS"
    assert rebound["current_date"] == "2024-12-03"
    assert rebound["last_closed_date"] == "2024-12-02"
    assert rebound["completed_units_in_current_date"] == 0
    assert rebound["completed_source_rows_in_current_date"] == 0
    assert rebound["output_shards"] == []
    assert rebound["last_completed"] is None
    assert rebound["next_exact_resume_point"]["selection_position"] == 0
    assert rebound["carry_by_ticker"] == cp["carry_by_ticker"]
    assert rebound["previous_date_close"] == cp["date_close"]
    assert "date_close" not in rebound
    assert rebound["software_revision"] == "new-head"


def test_rebind_rejects_in_progress_prior_boundary():
    cp = _closed_checkpoint()
    cp["status"] = "IN_PROGRESS"
    cp["next_exact_resume_point"] = {
        "selection_position": 2,
        "manifest_index": 2,
        "trading_date": "2024-12-02",
        "ticker": "CCCC",
        "data_row_count": 4,
        "first_clock_time": "09:00:00",
        "last_clock_time": "15:49:00",
        "source_row_first": 9,
        "source_row_last": 12,
    }
    with pytest.raises(RuntimeError, match="M2_NEXT_PRIOR_CHECKPOINT_NOT_DATE_CLOSED"):
        build_rebound_checkpoint(
            cp,
            expected_last_source="S1",
            expected_last_date="2024-12-02",
            successor={
                "source_name": "S1",
                "trading_date": "2024-12-03",
                "first_unit": FakeRow(2, "2024-12-03", "AAAA", 5, 9, 13).as_dict() | {"selection_position": 0},
            },
            new_identity=_identity(),
            transition_name="transition.json",
        )
