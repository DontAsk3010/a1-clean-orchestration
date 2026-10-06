from __future__ import annotations

import pytest

from a1clean.formula_research import machine2_current_store as store_module
from a1clean.formula_research.machine2_current_store import (
    MACHINE2_CHECKPOINT_FOLDER_ID,
    MACHINE2_GOVERNANCE_FOLDER_ID,
    MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
    V3_SCIENTIFIC_LINEAGE,
    Machine2CurrentStore,
    physical_name_for_current_execution,
)


HEAD = "1" * 40


def test_v3_semantic_shard_is_physically_generation_scoped_without_changing_lineage():
    logical = f"{V3_SCIENTIFIC_LINEAGE}__2024-12-02__SHARD_00001.jsonl"
    physical = physical_name_for_current_execution(
        MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
        logical,
        generation_id=HEAD,
    )
    assert physical == f"{V3_SCIENTIFIC_LINEAGE}__GEN_{HEAD}__2024-12-02__SHARD_00001.jsonl"
    assert physical.startswith(f"{V3_SCIENTIFIC_LINEAGE}__")


def test_v3_checkpoint_is_physically_generation_scoped():
    logical = f"{V3_SCIENTIFIC_LINEAGE}__CHECKPOINT_CURRENT.json"
    assert physical_name_for_current_execution(
        MACHINE2_CHECKPOINT_FOLDER_ID,
        logical,
        generation_id=HEAD,
    ) == f"{V3_SCIENTIFIC_LINEAGE}__GEN_{HEAD}__CHECKPOINT_CURRENT.json"


def test_generation_scoping_never_changes_governance_or_non_v3_names():
    governance_name = f"{V3_SCIENTIFIC_LINEAGE}__RECOVERY_PROOF.json"
    assert physical_name_for_current_execution(
        MACHINE2_GOVERNANCE_FOLDER_ID,
        governance_name,
        generation_id=HEAD,
    ) == governance_name
    v2_name = "MACHINE2_CURRENT_FULL_RESTART_FROM_BEGINNING_V2__CHECKPOINT_CURRENT.json"
    assert physical_name_for_current_execution(
        MACHINE2_CHECKPOINT_FOLDER_ID,
        v2_name,
        generation_id=HEAD,
    ) == v2_name


def test_generation_scoping_is_idempotent_for_already_physical_name():
    physical = f"{V3_SCIENTIFIC_LINEAGE}__GEN_{HEAD}__CHECKPOINT_CURRENT.json"
    assert physical_name_for_current_execution(
        MACHINE2_CHECKPOINT_FOLDER_ID,
        physical,
        generation_id=HEAD,
    ) == physical


def test_v3_durable_write_requires_exact_full_git_sha_generation(monkeypatch):
    logical = f"{V3_SCIENTIFIC_LINEAGE}__CHECKPOINT_CURRENT.json"
    monkeypatch.delenv("A1_M2_EXECUTION_GENERATION_ID", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    with pytest.raises(RuntimeError, match="M2_CURRENT_V3_EXECUTION_GENERATION_ID_REQUIRED"):
        physical_name_for_current_execution(
            MACHINE2_CHECKPOINT_FOLDER_ID,
            logical,
        )
    with pytest.raises(RuntimeError, match="M2_CURRENT_V3_EXECUTION_GENERATION_MUST_BE_EXACT_GIT_SHA"):
        physical_name_for_current_execution(
            MACHINE2_CHECKPOINT_FOLDER_ID,
            logical,
            generation_id="deadbeef",
        )



class _FakeRequest:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _FakeFiles:
    def __init__(self, state):
        self.state = state

    def create(self, *, body, media_body, fields, supportsAllDrives):
        def run():
            self.state["create_calls"] += 1
            payload = media_body.getbytes(0, media_body.size())
            self.state["exists"] = True
            self.state["bytes"] = payload
            if self.state.get("create_timeout_once"):
                self.state["create_timeout_once"] = False
                raise TimeoutError("The read operation timed out")
            return {
                "id": "file-1",
                "name": body["name"],
                "size": str(len(payload)),
                "md5Checksum": "md5",
                "parents": [self.state["folder_id"]],
                "mimeType": "application/json",
            }
        return _FakeRequest(run)

    def update(self, *, fileId, media_body, fields, supportsAllDrives):
        def run():
            self.state["update_calls"] += 1
            payload = media_body.getbytes(0, media_body.size())
            self.state["bytes"] = payload
            if self.state.get("update_timeout_once"):
                self.state["update_timeout_once"] = False
                raise TimeoutError("The read operation timed out")
            return {
                "id": fileId,
                "name": self.state["physical_name"],
                "size": str(len(payload)),
                "md5Checksum": "md5",
                "parents": [self.state["folder_id"]],
                "mimeType": "application/json",
            }
        return _FakeRequest(run)


class _FakeApi:
    def __init__(self, state):
        self._files = _FakeFiles(state)

    def files(self):
        return self._files


def _install_fake_store_transport(monkeypatch, state):
    def fake_list_children(api, folder_id, fields=None):
        if not state["exists"]:
            return []
        return [{
            "id": "file-1",
            "name": state["physical_name"],
            "mimeType": "application/json",
            "size": str(len(state["bytes"])),
            "md5Checksum": "md5",
            "modifiedTime": "2026-10-06T00:00:00Z",
            "parents": [folder_id],
        }]

    def fake_download_bytes(api, file_id):
        return state["bytes"]

    monkeypatch.setattr(store_module, "_list_children", fake_list_children)
    monkeypatch.setattr(store_module, "_download_bytes", fake_download_bytes)
    monkeypatch.setattr(store_module.time, "sleep", lambda _seconds: None)


def test_progressive_checkpoint_update_retries_same_file_after_read_timeout(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", HEAD)
    logical = f"{V3_SCIENTIFIC_LINEAGE}__CHECKPOINT_CURRENT.json"
    physical = physical_name_for_current_execution(
        MACHINE2_CHECKPOINT_FOLDER_ID,
        logical,
        generation_id=HEAD,
    )
    state = {
        "folder_id": MACHINE2_CHECKPOINT_FOLDER_ID,
        "physical_name": physical,
        "exists": True,
        "bytes": b'{"old":true}\n',
        "create_calls": 0,
        "update_calls": 0,
        "update_timeout_once": True,
    }
    _install_fake_store_transport(monkeypatch, state)
    store = Machine2CurrentStore(_FakeApi(state))

    receipt = store.upsert_json(
        folder_id=MACHINE2_CHECKPOINT_FOLDER_ID,
        name=logical,
        obj={"new": True},
    )

    assert state["create_calls"] == 0
    assert state["update_calls"] == 2
    assert state["bytes"] == b'{"new":true}\n'
    assert receipt["id"] == "file-1"
    assert receipt["name"] == physical


def test_ambiguous_create_timeout_reconciles_exact_object_without_duplicate(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", HEAD)
    logical = f"{V3_SCIENTIFIC_LINEAGE}__CHECKPOINT_CURRENT.json"
    physical = physical_name_for_current_execution(
        MACHINE2_CHECKPOINT_FOLDER_ID,
        logical,
        generation_id=HEAD,
    )
    state = {
        "folder_id": MACHINE2_CHECKPOINT_FOLDER_ID,
        "physical_name": physical,
        "exists": False,
        "bytes": b"",
        "create_calls": 0,
        "update_calls": 0,
        "create_timeout_once": True,
    }
    _install_fake_store_transport(monkeypatch, state)
    store = Machine2CurrentStore(_FakeApi(state))

    receipt = store.upsert_json(
        folder_id=MACHINE2_CHECKPOINT_FOLDER_ID,
        name=logical,
        obj={"first": True},
    )

    assert state["create_calls"] == 1
    assert state["update_calls"] == 0
    assert state["bytes"] == b'{"first":true}\n'
    assert receipt["id"] == "file-1"
    assert receipt["name"] == physical
