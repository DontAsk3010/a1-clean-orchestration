from a1clean.formula_research.haka_haki_reconstruction import reconstruct_bar


def test_reconstructs_proven_nonzero_flow() -> None:
    row = {
        "timestamp": "2024-12-02 09:00:00",
        "trade_value": 1000.0,
        "nbss": 200.0,
        "flow_available": True,
        "mechanism_eligible": True,
    }
    out = reconstruct_bar(row)
    assert out["status"] == "RECONSTRUCTED_PROVEN_SCOPE"
    assert out["haka"] == 600.0
    assert out["haki"] == 400.0


def test_zero_without_independent_availability_stays_unknown() -> None:
    row = {
        "trade_value": 1000.0,
        "nbss": 0.0,
        "flow_available": False,
        "mechanism_eligible": False,
    }
    out = reconstruct_bar(row)
    assert out["status"] == "ZERO_AVAILABILITY_UNPROVEN"
    assert out["haka"] is None
    assert out["haki"] is None


def test_impossible_signed_imbalance_is_rejected() -> None:
    row = {
        "trade_value": 100.0,
        "nbss": 150.0,
        "flow_available": True,
        "mechanism_eligible": True,
    }
    out = reconstruct_bar(row)
    assert out["status"] == "INVALID_NEGATIVE_DERIVED_SIDE"
