from a1clean.formula_research.haka_haki_behavior_lane import enrich_formation_chronology, formation_window_summary


def _bar(close: float, value: float, nbss: float, available: bool = True) -> dict:
    return {
        "close": close,
        "trade_value": value,
        "nbss": nbss,
        "flow_available": available,
        "mechanism_eligible": available,
    }


def test_chronology_preserves_price_and_formation_together() -> None:
    rows = enrich_formation_chronology([
        _bar(100.0, 1000.0, 200.0),
        _bar(101.0, 1200.0, -200.0),
    ])
    assert rows[0]["haka"] == 600.0
    assert rows[0]["haki"] == 400.0
    assert rows[1]["haka"] == 500.0
    assert rows[1]["haki"] == 700.0
    assert rows[1]["price_delta_pct"] == 1.0
    assert rows[1]["formation_coverage_fraction"] == 1.0


def test_unknown_zero_is_not_folded_into_effort() -> None:
    rows = enrich_formation_chronology([
        _bar(100.0, 1000.0, 200.0),
        _bar(100.0, 900.0, 0.0, available=False),
    ])
    assert rows[1]["haka"] is None
    assert rows[1]["haki"] is None
    assert rows[1]["formation_coverage_fraction"] == 0.5
    summary = formation_window_summary(rows)
    assert summary["valid_haka_haki_rows"] == 1
    assert summary["coverage_fraction"] == 0.5
    assert summary["trade_value"] == 1000.0
    assert summary["nbss"] == 200.0
