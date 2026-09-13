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
)
INTAKE_REQUIRED_ANCHORS = (
    "CURRENT_READY_UNIVERSE_AT_FIRST_ACTIVATION_IS_BASELINE_NOT_RETROACTIVELY_AUTO_QUEUED",
    "discover_governed_ready_sources",
    "find_verified_pass_checkpoint",
    "run_governed_auto_continuation",
    "RESUME_AUTOMATIC_INTAKE_FROM_PERSISTED_SOURCE_AND_DATE_CHECKPOINTS_DO_NOT_RESTART_ACCEPTED_WORK",
)

# The existing repair agent remains token-bounded and governance-bounded. This wrapper
# only extends its operational allowlist to the new intake controller and classifies
# intake identity/governance failures as hard holds rather than model-repair candidates.
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
        for anchor in INTAKE_REQUIRED_ANCHORS:
            if anchor not in new:
                raise RuntimeError(f"SELF_HEAL_INTAKE_INVARIANT_REMOVED:{anchor}")


self_heal._guard_replacement = _intake_guard_replacement


def main(argv: list[str] | None = None) -> int:
    return self_heal.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
