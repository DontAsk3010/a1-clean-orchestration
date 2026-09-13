from __future__ import annotations

from . import self_heal

INTAKE_REPAIR_PATH = "src/a1clean/pattern_discovery/intake.py"
INTAKE_HARD_HOLD_MARKERS = (
    "AUTOMATIC_INTAKE_DUPLICATE_SOURCE_NAME",
    "AUTOMATIC_INTAKE_DUPLICATE_CONTENT",
    "AUTOMATIC_INTAKE_GOVERNED_READY_INVARIANT_FAILED",
    "AUTOMATIC_INTAKE_STATE_SCHEMA_OR_LANE_MISMATCH",
    "AUTOMATIC_INTAKE_STATE_PLAN_FINGERPRINT_MISMATCH",
    "AUTOMATIC_INTAKE_STATE_SHARD_POLICY_MISMATCH",
    "AUTOMATIC_INTAKE_PLAN_FINGERPRINT_MISMATCH",
    "AUTOMATIC_INTAKE_SOURCE_IDENTITY_CHANGED_DURING_ADMISSION",
    "AUTOMATIC_INTAKE_SOURCE_COVERAGE_MISSING",
)
INTAKE_REQUIRED_ANCHORS = (
    "ALL_CURRENT_AND_FUTURE_GOVERNED_READY_SOURCES_MUST_REACH_CORPUS_COMPLETE",
    "FIRST_GOVERNED_TRADING_DATE_THEN_LAST_GOVERNED_TRADING_DATE_NOT_FILENAME",
    "QUEUED_EXISTING_GOVERNED_SOURCE",
    "discover_governed_ready_sources",
    "order_source_queue",
    "find_verified_pass_checkpoint",
    "run_governed_auto_continuation",
    "RESUME_AUTOMATIC_INTAKE_FROM_PERSISTED_SOURCE_AND_DATE_CHECKPOINTS_DO_NOT_RESTART_ACCEPTED_WORK",
)
FORBIDDEN_REINTRODUCED_INTAKE_POLICIES = (
    'baseline_policy": "CURRENT_READY_UNIVERSE_AT_FIRST_ACTIVATION_IS_BASELINE_NOT_RETROACTIVELY_AUTO_QUEUED"',
    "unchanged baseline/complete = noop",
)

# Extend the already token-bounded operational repair agent only to intake plumbing.
self_heal.ALLOWED_REPAIR_PATHS = tuple(
    dict.fromkeys((*self_heal.ALLOWED_REPAIR_PATHS, INTAKE_REPAIR_PATH))
)
self_heal.HARD_HOLD_MARKERS = tuple(
    dict.fromkeys((*self_heal.HARD_HOLD_MARKERS, *INTAKE_HARD_HOLD_MARKERS))
)

_original_guard_replacement = self_heal._guard_replacement


def _intake_guard_replacement(*, path: str, old: str, new: str) -> None:
    _original_guard_replacement(path=path, old=old, new=new)
    if path == INTAKE_REPAIR_PATH:
        lower = new.lower()
        for anchor in INTAKE_REQUIRED_ANCHORS:
            if anchor not in new:
                raise RuntimeError(f"SELF_HEAL_INTAKE_INVARIANT_REMOVED:{anchor}")
        for forbidden in FORBIDDEN_REINTRODUCED_INTAKE_POLICIES:
            if forbidden.lower() in lower:
                raise RuntimeError(f"SELF_HEAL_INTAKE_SUPERSEDED_POLICY_REINTRODUCED:{forbidden}")


self_heal._guard_replacement = _intake_guard_replacement


def main(argv: list[str] | None = None) -> int:
    return self_heal.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
