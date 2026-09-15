from a1clean.formula_research.mg_v5_candidate_freezer import freeze_report


def _report():
    return {
        "schema": "A1_TELEGRAM_MG_OUTCOME_FIRST_DISCOVERY_V5",
        "request_id": "REQ",
        "march_2025_oos_touched": False,
        "future_data_used_for_formula_state": False,
        "candidate_table": [
            {
                "parts": ["CUR_FLOW", "PRIOR3_RECLAIM"],
                "cross_period_pass": True,
                "strict_q25_cross_period_pass": True,
                "min_period_q25_net_mfe": 0.11,
                "min_period_median_net_mfe": 0.62,
                "min_period_positive_rate": 0.61,
                "total_evaluable": 120,
            },
            {
                "parts": ["CUR_VALUE"],
                "cross_period_pass": True,
                "strict_q25_cross_period_pass": False,
                "min_period_q25_net_mfe": -0.1,
                "min_period_median_net_mfe": 0.25,
                "min_period_positive_rate": 0.55,
                "total_evaluable": 300,
            },
        ],
    }


def test_freezer_emits_only_strict_candidates_by_default():
    pack = freeze_report(_report())
    assert pack["formula_count"] == 1
    assert pack["formulas"][0]["spec"]["required"] == ["CUR_FLOW", "PRIOR3_RECLAIM"]
    assert pack["formulas"][0]["afl_boolean_expression"] == "(S_CUR_FLOW AND S_PRIOR3_RECLAIM)"
    assert pack["future_data_in_executable_formula"] is False


def test_freezer_can_export_nonstrict_research_candidates_without_promoting_live():
    pack = freeze_report(_report(), strict_only=False)
    assert pack["formula_count"] == 2
    assert pack["promotion_to_live_allowed"] is False


def test_freezer_rejects_future_leakage_and_oos_integrity_break():
    r = _report()
    r["future_data_used_for_formula_state"] = True
    try:
        freeze_report(r)
    except ValueError as e:
        assert str(e) == "FORMULA_STATE_FUTURE_LEAKAGE"
    else:
        raise AssertionError("expected leakage rejection")

    r = _report()
    r["march_2025_oos_touched"] = True
    try:
        freeze_report(r)
    except ValueError as e:
        assert str(e) == "OOS_INTEGRITY_NOT_PROVEN"
    else:
        raise AssertionError("expected OOS integrity rejection")
