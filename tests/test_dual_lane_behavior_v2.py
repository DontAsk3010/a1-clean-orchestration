from a1clean.formula_research import dual_lane_behavior_v2 as v2


def test_missing_flow_window_is_unknown_not_zero():
    out = v2._window_formation(
        value=100.0,
        volume=20.0,
        nbss=0.0,
        flow_rows=0,
        rows=5,
        flow_sign_changes=0,
        prev_value=40.0,
        prev_volume=8.0,
        prev_nbss=0.0,
        prev_flow_rows=0,
        prev_rows=2,
        prev_flow_sign_changes=0,
    )
    assert out["window_trade_value"] == 60.0
    assert out["window_volume"] == 12.0
    assert out["window_nbss"] is None
    assert out["window_abs_nbss"] is None
    assert out["window_nbss_to_value"] is None
    assert out["flow_coverage_fraction"] == 0.0


def test_price_and_formation_are_read_together():
    snapshot = {
        "price": {"direction": "UP"},
        "formation": {
            "window_nbss": 25.0,
            "formation_rising_vs_prev_pub": True,
        },
        "rank_buckets": {
            "window_trade_value": "Q4",
            "window_volume": "Q3",
            "window_abs_nbss": "Q4",
        },
    }
    assert v2._relation_state(snapshot, None) == "ALIGNED_FORMATION_AND_PRICE_ADVANCE"


def test_same_price_direction_can_encode_different_formation_behavior():
    buy_supported = {
        "price": {"direction": "UP"},
        "formation": {
            "window_nbss": 20.0,
            "formation_rising_vs_prev_pub": True,
        },
        "rank_buckets": {
            "window_trade_value": "Q4",
            "window_volume": "Q4",
            "window_abs_nbss": "Q4",
        },
    }
    sell_resilient = {
        "price": {"direction": "UP"},
        "formation": {
            "window_nbss": -20.0,
            "formation_rising_vs_prev_pub": True,
        },
        "rank_buckets": {
            "window_trade_value": "Q4",
            "window_volume": "Q4",
            "window_abs_nbss": "Q4",
        },
    }
    assert v2._relation_state(buy_supported, None) == "ALIGNED_FORMATION_AND_PRICE_ADVANCE"
    assert v2._relation_state(sell_resilient, None) == "SELL_FLOW_WITH_PRICE_RESILIENCE"


def test_delayed_price_response_is_sequence_dependent():
    prev = {"relation_state": "BUY_FLOW_WITHOUT_PRICE_PROGRESS"}
    snapshot = {
        "price": {"direction": "UP"},
        "formation": {
            "window_nbss": 15.0,
            "formation_rising_vs_prev_pub": True,
        },
        "rank_buckets": {
            "window_trade_value": "Q4",
            "window_volume": "Q3",
            "window_abs_nbss": "Q4",
        },
    }
    assert v2._relation_state(snapshot, prev) == "DELAYED_UP_RESPONSE_AFTER_BUY_FLOW"


def test_compressed_relation_sequence_keeps_latest_occurrence_index():
    snaps = [
        {"relation_state": "A"},
        {"relation_state": "A"},
        {"relation_state": "B"},
        {"relation_state": "B"},
        {"relation_state": "C"},
    ]
    assert v2._compressed_relation_occurrences(snaps) == [("A", 1), ("B", 3), ("C", 4)]
