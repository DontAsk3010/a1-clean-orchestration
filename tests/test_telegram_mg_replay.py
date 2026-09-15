from a1clean.formula_research.handbook_candidates import CandidateParams, TRUE, UNKNOWN
from a1clean.formula_research.telegram_mg_replay import evaluate_mg_packet


def _params():
    return CandidateParams(
        effort_lookback=3,
        progress_lookback=3,
        high_lookback=3,
        recovery_lookback=3,
        low_stabilization_bars=2,
        early_checkpoint_bar=3,
        late_lift_min_bar=8,
    )


def _bar(i, close, high, low, value, nbss, minute):
    return {
        "trading_date": "2024-12-02",
        "open": close - 0.5,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000 + i,
        "trade_value": value,
        "nbss": nbss,
        "flow_available": True,
        "mechanism_eligible": True,
        "session_eligible": True,
        "canonical_vwap": None,
        "timestamp": f"2024-12-02 09:{minute:02d}:00",
    }


def test_mg_path_value_buy_response_becomes_true_causally():
    bars = [
        _bar(0, 100.0, 101.0, 99.0, 100.0, 20.0, 0),
        _bar(1, 100.5, 101.0, 100.0, 110.0, 20.0, 1),
        _bar(2, 101.0, 101.5, 100.5, 120.0, 20.0, 2),
        _bar(3, 101.5, 102.0, 101.0, 200.0, 50.0, 3),
        _bar(4, 102.0, 102.5, 101.5, 220.0, 60.0, 4),
        _bar(5, 102.5, 103.0, 102.0, 260.0, 80.0, 5),
    ]
    rows = evaluate_mg_packet(bars, _params())
    last = rows[-1]
    assert last["components"]["UP_PATH"] == TRUE
    assert last["components"]["MULTIBAR_PERSISTENCE"] == TRUE
    assert last["components"]["VALUE_EXPANSION"] == TRUE
    assert last["components"]["BUY_RESPONSE"] == TRUE
    assert last["variants"]["MG_D_PATH_VALUE_FLOW"] == TRUE
    assert last["variants"]["MG_G_BUY_RESPONSE_PATH"] == TRUE
    assert last["publication_slot"] is True
    assert last["targets"]["tp2"] > last["targets"]["tp1"] > bars[-1]["close"]


def test_unproven_flow_does_not_silently_pass_flow_variant():
    bars = [
        _bar(0, 100.0, 101.0, 99.0, 100.0, 20.0, 0),
        _bar(1, 100.5, 101.0, 100.0, 110.0, 20.0, 1),
        _bar(2, 101.0, 101.5, 100.5, 120.0, 20.0, 2),
        _bar(3, 101.5, 102.0, 101.0, 200.0, 50.0, 3),
    ]
    bars[-1]["flow_available"] = False
    rows = evaluate_mg_packet(bars, _params())
    assert rows[-1]["components"]["CONSTRUCTIVE_FLOW"] == UNKNOWN
    assert rows[-1]["variants"]["MG_D_PATH_VALUE_FLOW"] == UNKNOWN
