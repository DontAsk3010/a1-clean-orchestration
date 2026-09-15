from a1clean.formula_research.telegram_mg_profit_qualified_v1 import (
    _execution_net,
    _observed_price_step,
    _quantile,
)


def test_quantile_interpolates_deterministically():
    values = [0.0, 1.0, 2.0, 3.0, 4.0]
    assert _quantile(values, 0.25) == 1.0
    assert _quantile(values, 0.50) == 2.0


def test_observed_price_step_uses_only_data_through_index():
    bars = [
        {"open": 100.0, "high": 102.0, "low": 100.0, "close": 102.0},
        {"open": 102.0, "high": 104.0, "low": 102.0, "close": 104.0},
        {"open": 104.0, "high": 105.0, "low": 104.0, "close": 105.0},
        {"open": 105.0, "high": 105.5, "low": 105.0, "close": 105.5},
    ]
    assert _observed_price_step(bars, 2) == 1.0
    assert _observed_price_step(bars, 3) == 0.5


def test_execution_net_applies_buy_and_sell_fees():
    result = _execution_net(100.0, 102.0, 1000, 0.15, 0.25)
    assert result["gross_pl"] == 2000.0
    assert round(result["buy_fee"], 2) == 150.0
    assert round(result["sell_fee"], 2) == 255.0
    assert round(result["net_pl"], 2) == 1595.0
