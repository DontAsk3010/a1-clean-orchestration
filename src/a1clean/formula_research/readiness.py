from __future__ import annotations

from dataclasses import dataclass


class FormulaResearchContractError(ValueError):
    """Fail-closed contract violation for current-clean formula research."""


@dataclass(frozen=True)
class FormulaReadinessInput:
    owner_formula_research_authorized: bool
    lane2_universe_corpus_complete: bool
    lane2_hold: bool
    semantic_corpus_complete: bool
    cross_ticker_reconciliation_complete: bool
    cross_date_reconciliation_complete: bool
    cross_month_atlas_complete: bool
    current_execution_formula_gate_open: bool


def assess_formula_readiness(state: FormulaReadinessInput) -> dict[str, object]:
    """Separate work that is safe now from gates required for a final formula.

    Lane 2 structural translation may begin once the owner has authorized formula
    research and the current governed-ready Lane 2 universe is complete/clean.
    Final formula construction remains fail-closed until the semantic corpus and
    its temporal reconciliations are complete and Current Execution opens the
    formula gate.
    """

    translation_blockers: list[str] = []
    if not state.owner_formula_research_authorized:
        translation_blockers.append("OWNER_FORMULA_RESEARCH_AUTHORIZATION_REQUIRED")
    if not state.lane2_universe_corpus_complete:
        translation_blockers.append("LANE2_CURRENT_GOVERNED_READY_UNIVERSE_NOT_COMPLETE")
    if state.lane2_hold:
        translation_blockers.append("LANE2_HOLD_PRESENT")

    translation_allowed = not translation_blockers

    final_blockers = list(translation_blockers)
    semantic_requirements = (
        (state.semantic_corpus_complete, "SEMANTIC_CORPUS_NOT_COMPLETE"),
        (state.cross_ticker_reconciliation_complete, "CROSS_TICKER_RECONCILIATION_NOT_COMPLETE"),
        (state.cross_date_reconciliation_complete, "CROSS_DATE_RECONCILIATION_NOT_COMPLETE"),
        (state.cross_month_atlas_complete, "CROSS_MONTH_ATLAS_NOT_COMPLETE"),
        (state.current_execution_formula_gate_open, "CURRENT_EXECUTION_FORMULA_GATE_NOT_OPEN"),
    )
    for passed, blocker in semantic_requirements:
        if not passed:
            final_blockers.append(blocker)

    final_formula_allowed = not final_blockers

    return {
        "schema": "A1_CURRENT_CLEAN_FORMULA_RESEARCH_READINESS_V1",
        "translation_measurement_allowed": translation_allowed,
        "candidate_state_specification_allowed": translation_allowed,
        "final_formula_construction_allowed": final_formula_allowed,
        "trading_signal_activation_allowed": False,
        "telegram_formula_activation_allowed": False,
        "translation_blockers": translation_blockers,
        "final_formula_blockers": final_blockers,
        "status": (
            "FINAL_FORMULA_READY"
            if final_formula_allowed
            else "TRANSLATION_RESEARCH_OPEN_FINAL_FORMULA_HOLD"
            if translation_allowed
            else "FORMULA_RESEARCH_HOLD"
        ),
    }
