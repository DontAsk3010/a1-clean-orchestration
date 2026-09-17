from a1clean.formula_research.v30_semantic_journey_enrichment import enrich_ticker_day


def _bar(ts, o, h, l, c, vol, val, nbss=None, flow=False):
    return {
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": vol,
        "trade_value": val,
        "nbss": nbss,
        "flow_available": flow,
        "mechanism_eligible": flow,
    }


def test_zero_session_is_preserved_without_forced_event():
    day, runs, journeys = enrich_ticker_day(
        [],
        source="X.csv",
        source_identity={},
        ticker="AAAA",
        trading_date="2025-01-02",
        carry_in=None,
        previous_governed_date=None,
        allow_haka_haki=False,
    )
    assert day["zero_session_eligible"] is True
    assert day["no_forced_event"] is True
    assert runs == []
    assert journeys == []


def test_causal_runs_and_hindsight_resolution_are_separate():
    bars = [
        _bar("2025-01-02T09:00:00", 100, 101, 100, 101, 10, 1000),
        _bar("2025-01-02T09:01:00", 101, 101, 99, 99, 11, 1100),
        _bar("2025-01-02T09:02:00", 99, 102, 99, 102, 12, 1200),
    ]
    day, runs, journeys = enrich_ticker_day(
        bars,
        source="X.csv",
        source_identity={},
        ticker="AAAA",
        trading_date="2025-01-02",
        carry_in=None,
        previous_governed_date=None,
        allow_haka_haki=False,
    )
    assert day["bar_count"] == 3
    assert runs
    assert all(run["causal_only"] is True for run in runs)
    recovery = [j for j in journeys if j["journey_kind"] == "RECOVERY"]
    assert recovery
    assert recovery[0]["future_resolution_not_used_to_define_start"] is True
    assert "hindsight_resolution" in recovery[0]


def test_open_break_reclaim_and_gap_uncertainty_are_recorded():
    bars = [
        _bar("2025-01-02T09:00:00", 100, 101, 100, 101, 10, 1000),
        _bar("2025-01-02T09:01:00", 101, 101, 98, 99, 11, 1100),
        _bar("2025-01-02T09:03:00", 99, 102, 99, 101, 12, 1200),
    ]
    day, _runs, journeys = enrich_ticker_day(
        bars,
        source="X.csv",
        source_identity={},
        ticker="AAAA",
        trading_date="2025-01-02",
        carry_in=None,
        previous_governed_date=None,
        allow_haka_haki=False,
    )
    assert day["timestamp_discontinuity_marker_count"] == 1
    obr = [j for j in journeys if j["journey_kind"] == "OPEN_BREAK_RECLAIM"]
    assert len(obr) == 1
    assert obr[0]["hindsight_resolution"]["resolution_status"] == "OPEN_RECLAIMED"
