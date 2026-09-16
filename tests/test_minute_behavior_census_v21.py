from a1clean.formula_research.minute_behavior_census_v21 import scan_ticker_day


def _bar(ts: str, close: float, *, volume: float, value: float, nbss: float, flow: bool = True) -> dict:
    return {
        "timestamp": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "trade_value": value,
        "nbss": nbss,
        "flow_available": flow,
        "mechanism_eligible": flow,
    }


def test_every_minute_is_accounted_and_temporal_runs_are_exact() -> None:
    bars = [
        _bar("2024-12-02 09:00:00", 100.0, volume=10, value=1000, nbss=200),
        _bar("2024-12-02 09:01:00", 100.0, volume=12, value=1200, nbss=300),
        _bar("2024-12-02 09:02:00", 101.0, volume=15, value=1500, nbss=400),
        _bar("2024-12-02 09:03:00", 100.0, volume=16, value=1600, nbss=-200),
    ]
    summary, runs = scan_ticker_day(bars, allow_haka_haki=True)
    assert summary["rows"] == 4
    assert summary["session_evidence_status"] == "AVAILABLE"
    assert summary["first_timestamp"] == "2024-12-02 09:00:00"
    assert summary["last_timestamp"] == "2024-12-02 09:03:00"
    assert summary["flow_rows"] == 4
    assert summary["haka_haki_rows"] == 4
    assert summary["relation_state_counts"]["BUY_FLOW_PRICE_NON_RESPONSE_OR_ADVERSE"] == 1
    assert summary["relation_state_counts"]["BUY_FLOW_PRICE_ADVANCE"] == 1
    assert summary["relation_state_counts"]["SELL_FLOW_PRICE_DECLINE"] == 1
    assert runs[0]["start_timestamp"] == "2024-12-02 09:00:00"
    assert runs[-1]["end_timestamp"] == "2024-12-02 09:03:00"
    assert len(summary["minute_evidence_digest_sha256"]) == 64


def test_unproven_zero_flow_is_not_treated_as_neutral() -> None:
    bars = [
        _bar("2024-12-02 09:00:00", 100.0, volume=10, value=1000, nbss=200),
        _bar("2024-12-02 09:01:00", 100.0, volume=10, value=1000, nbss=0, flow=False),
    ]
    summary, runs = scan_ticker_day(bars, allow_haka_haki=True)
    assert summary["rows"] == 2
    assert summary["flow_rows"] == 1
    assert summary["haka_haki_rows"] == 1
    assert summary["haka_haki_reconstruction_status_counts"]["ZERO_AVAILABILITY_UNPROVEN"] == 1
    assert summary["relation_state_counts"]["NO_PROVEN_FLOW"] == 1
    assert all(run["state"] != "PROVEN_NEUTRAL_FLOW" for run in runs)


def test_non_proven_source_does_not_reconstruct_haka_haki() -> None:
    bars = [_bar("2025-01-02 09:00:00", 100.0, volume=10, value=1000, nbss=200)]
    summary, _ = scan_ticker_day(bars, allow_haka_haki=False)
    assert summary["haka_haki_proven_source_scope"] is False
    assert summary["haka_haki_rows"] == 0
    assert summary["haka_sum"] is None
    assert summary["haki_sum"] is None
    assert summary["haka_haki_reconstruction_status_counts"]["NOT_IN_PROVEN_HAKA_HAKI_SOURCE_SCOPE"] == 1


def test_zero_session_bar_ticker_day_is_preserved_as_processed_unknown_evidence() -> None:
    summary, runs = scan_ticker_day([], allow_haka_haki=True)
    assert summary["rows"] == 0
    assert summary["session_evidence_status"] == "NO_SESSION_ELIGIBLE_BARS"
    assert summary["first_timestamp"] is None
    assert summary["last_timestamp"] is None
    assert summary["flow_rows"] == 0
    assert summary["haka_haki_rows"] == 0
    assert summary["first_relation_state"] is None
    assert summary["last_relation_state"] is None
    assert summary["minute_evidence_digest_sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert runs == []
