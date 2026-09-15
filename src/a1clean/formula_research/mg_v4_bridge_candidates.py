from __future__ import annotations

from .mg_formula_candidate_spec import MGFormulaCandidateSpec


# These are research bridge candidates extracted from V4 backward-sequence
# discovery. They are intentionally NOT canonical/live formulas. Their purpose
# is to give the next research stage a concrete executable baseline while V5
# mines failure discriminators across the full universe.

MG_RR_FLOW_RENEW_V4 = MGFormulaCandidateSpec(
    formula_id="MG_RR_FLOW_RENEW_V4",
    required=(
        "HELD_FLOW",
        "PRIOR3_RECLAIM",
        "REGAIN_RENEWED_HIGH",
    ),
)

MG_RR_FLOW_FRESH_V4 = MGFormulaCandidateSpec(
    formula_id="MG_RR_FLOW_FRESH_V4",
    required=(
        "HELD_FLOW",
        "PRIOR3_RECLAIM",
        "REGAIN_FRESH",
    ),
)

V4_BRIDGE_CANDIDATES = (
    MG_RR_FLOW_RENEW_V4,
    MG_RR_FLOW_FRESH_V4,
)
