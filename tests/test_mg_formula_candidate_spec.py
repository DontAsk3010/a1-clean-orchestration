from a1clean.formula_research.mg_formula_candidate_spec import (
    MGFormulaCandidateSpec,
    evaluate_first_matches,
    spec_from_v5_candidate,
    to_afl_boolean_expression,
)


def test_candidate_matches_required_and_forbidden_markers():
    spec = MGFormulaCandidateSpec(
        formula_id="MG_TEST",
        required=("CUR_FLOW", "CUR_RECLAIM"),
        forbidden=("TIME_14_PLUS",),
    )
    assert spec.matches({"CUR_FLOW", "CUR_RECLAIM", "CUR_VALUE"})
    assert not spec.matches({"CUR_FLOW"})
    assert not spec.matches({"CUR_FLOW", "CUR_RECLAIM", "TIME_14_PLUS"})


def test_first_match_semantics_emit_only_first_causal_occurrence():
    spec = MGFormulaCandidateSpec(formula_id="MG_TEST", required=("CUR_FLOW",))
    rows = [set(), {"CUR_FLOW"}, {"CUR_FLOW"}, set(), {"CUR_FLOW"}]
    assert evaluate_first_matches(rows, spec) == (False, True, False, False, False)


def test_afl_expression_uses_same_marker_names():
    spec = MGFormulaCandidateSpec(
        formula_id="MG_TEST",
        required=("CUR_FLOW", "REGAIN_FRESH"),
        forbidden=("TIME_14_PLUS",),
    )
    assert to_afl_boolean_expression(spec) == (
        "(S_CUR_FLOW AND S_REGAIN_FRESH) AND (NOT S_TIME_14_PLUS)"
    )


def test_v5_candidate_freeze_copies_only_signature_parts():
    row = {
        "parts": ["CUR_FLOW", "PRIOR3_RECLAIM"],
        "min_period_median_net_mfe": 1.23,
        "cross_period_pass": True,
    }
    spec = spec_from_v5_candidate(row, formula_id="MG_V5_001")
    assert spec.required == ("CUR_FLOW", "PRIOR3_RECLAIM")
    assert "min_period_median_net_mfe" not in spec.to_dict()
    assert spec.to_dict()["future_data_used_for_formula_state"] is False
