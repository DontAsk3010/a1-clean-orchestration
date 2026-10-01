from __future__ import annotations

import pytest

from a1clean.formula_research.machine2_current_store import (
    MACHINE2_CHECKPOINT_FOLDER_ID,
    MACHINE2_GOVERNANCE_FOLDER_ID,
    MACHINE2_SEMANTIC_OUTPUT_FOLDER_ID,
    V3_SCIENTIFIC_LINEAGE,
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


def test_v3_durable_write_requires_exact_full_git_sha_generation():
    logical = f"{V3_SCIENTIFIC_LINEAGE}__CHECKPOINT_CURRENT.json"
    with pytest.raises(RuntimeError, match="M2_CURRENT_V3_EXECUTION_GENERATION_ID_REQUIRED"):
        physical_name_for_current_execution(
            MACHINE2_CHECKPOINT_FOLDER_ID,
            logical,
            generation_id=None,
        )
    with pytest.raises(RuntimeError, match="M2_CURRENT_V3_EXECUTION_GENERATION_MUST_BE_EXACT_GIT_SHA"):
        physical_name_for_current_execution(
            MACHINE2_CHECKPOINT_FOLDER_ID,
            logical,
            generation_id="deadbeef",
        )
