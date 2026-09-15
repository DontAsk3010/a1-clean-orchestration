from a1clean.formula_research.mg_formula_candidate_spec import evaluate_first_matches, to_afl_boolean_expression
from a1clean.formula_research.mg_v4_bridge_candidates import (
    MG_RR_FLOW_FRESH_V4,
    MG_RR_FLOW_RENEW_V4,
)


def test_v4_renew_candidate_requires_exact_sequence_core():
    good = {"HELD_FLOW", "PRIOR3_RECLAIM", "REGAIN_RENEWED_HIGH", "CUR_VALUE"}
    missing = {"HELD_FLOW", "PRIOR3_RECLAIM"}
    assert MG_RR_FLOW_RENEW_V4.matches(good)
    assert not MG_RR_FLOW_RENEW_V4.matches(missing)


def test_v4_fresh_candidate_requires_exact_sequence_core():
    good = {"HELD_FLOW", "PRIOR3_RECLAIM", "REGAIN_FRESH"}
    assert MG_RR_FLOW_FRESH_V4.matches(good)


def test_v4_candidates_enforce_first_causal_match():
    rows = [
        set(),
        {"HELD_FLOW", "PRIOR3_RECLAIM", "REGAIN_RENEWED_HIGH"},
        {"HELD_FLOW", "PRIOR3_RECLAIM", "REGAIN_RENEWED_HIGH"},
    ]
    assert evaluate_first_matches(rows, MG_RR_FLOW_RENEW_V4) == (False, True, False)


def test_v4_candidate_afl_expression_is_deterministic():
    assert to_afl_boolean_expression(MG_RR_FLOW_RENEW_V4) == (
        "(S_HELD_FLOW AND S_PRIOR3_RECLAIM AND S_REGAIN_RENEWED_HIGH)"
    )
