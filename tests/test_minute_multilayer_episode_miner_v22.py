from a1clean.formula_research.minute_multilayer_episode_miner_v22 import mine_ticker_day


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


def test_buy_nonresponse_then_response_preserves_exact_1m_latency() -> None:
    bars = [
        _bar("2024-12-02 09:00:00", 100.0, volume=10, value=1000, nbss=200),
        _bar("2024-12-02 09:01:00", 100.0, volume=12, value=1200, nbss=300),
        _bar("2024-12-02 09:02:00", 101.0, volume=15, value=1500, nbss=400),
    ]
    summary, runs = mine_ticker_day(bars, allow_haka_haki=True)
    assert summary["rows"] == 3
    assert summary["milestones"]["FIRST_BUY_NON_RESPONSE_TIME"] == "2024-12-02 09:01:00"
    assert summary["milestones"]["FIRST_BUY_PRICE_RESPONSE_TIME"] == "2024-12-02 09:02:00"
    event = summary["response_latency_events"][0]
    assert event["kind"] == "BUY_NONRESPONSE_TO_ADVANCE"
    assert event["start_timestamp"] == "2024-12-02 09:01:00"
    assert event["response_timestamp"] == "2024-12-02 09:02:00"
    assert event["latency_rows"] == 1
    assert runs[-1]["end_timestamp"] == "2024-12-02 09:02:00"


def test_sell_resilience_then_decline_is_kept_as_distinct_episode() -> None:
    bars = [
        _bar("2024-12-02 09:00:00", 100.0, volume=10, value=1000, nbss=-100),
        _bar("2024-12-02 09:01:00", 100.0, volume=11, value=1100, nbss=-200),
        _bar("2024-12-02 09:02:00", 99.0, volume=13, value=1300, nbss=-300),
    ]
    summary, _ = mine_ticker_day(bars, allow_haka_haki=True)
    assert summary["milestones"]["FIRST_SELL_RESILIENCE_TIME"] == "2024-12-02 09:01:00"
    assert summary["milestones"]["FIRST_SELL_PRICE_RESPONSE_TIME"] == "2024-12-02 09:02:00"
    event = summary["response_latency_events"][0]
    assert event["kind"] == "SELL_RESILIENCE_TO_DECLINE"
    assert event["latency_rows"] == 1


def test_unproven_flow_stays_unknown_and_no_haka_haki_is_invented() -> None:
    bars = [_bar("2025-01-02 09:00:00", 100.0, volume=10, value=1000, nbss=0, flow=False)]
    summary, runs = mine_ticker_day(bars, allow_haka_haki=False)
    assert summary["rows"] == 1
    assert summary["haka_haki_proven_source_scope"] is False
    assert "NO_PROVEN_FLOW" in runs[0]["token"]
    assert "FLOW_UNKNOWN" in runs[0]["token"]
    assert "HH_UNKNOWN" in runs[0]["token"]


def test_zero_session_ticker_day_is_processed_not_dropped() -> None:
    summary, runs = mine_ticker_day([], allow_haka_haki=False)
    assert summary["rows"] == 0
    assert summary["zero_session_eligible"] is True
    assert summary["episode_run_count"] == 0
    assert runs == []
    assert len(summary["episode_evidence_digest_sha256"]) == 64
