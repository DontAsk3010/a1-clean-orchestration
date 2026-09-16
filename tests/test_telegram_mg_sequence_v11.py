from a1clean.formula_research import telegram_mg_sequence_v11 as v11
from a1clean.formula_research.telegram_mg_question_driven_v10 import DayBehavior


def _d(date: str, *, low: float, close: float, rng: float, value: float, volume: float, nbss: float | None, pos: float | None, sellres: float | None, loc: float) -> DayBehavior:
    return DayBehavior(
        date=date,
        open=100.0,
        high=max(close, low) + 2.0,
        low=low,
        close=close,
        ret_pct=close - 100.0,
        range_pct=rng,
        close_location=loc,
        value=value,
        volume=volume,
        nbss=nbss,
        positive_nbss_bar_fraction=pos,
        negative_nbss_bar_fraction=None,
        down_bar_positive_nbss_fraction=None,
        sell_pressure_resilience_fraction=sellres,
        buy_effort_no_progress_fraction=None,
        late_nbss_to_value=None,
    )


def test_governed_blocks_are_fixed_and_oos_excluded():
    assert len(v11.DISCOVERY) == 10
    assert len(v11.VALIDATION_A) == 3
    assert len(v11.VALIDATION_B) == 4
    assert v11.RESERVED_OOS not in (v11.DISCOVERY + v11.VALIDATION_A + v11.VALIDATION_B)


def test_quiet_money_precondition_detects_contraction_and_value_build():
    h = [
        _d("1", low=95, close=103, rng=8, value=100, volume=100, nbss=1, pos=.4, sellres=.1, loc=.5),
        _d("2", low=95, close=97, rng=7, value=100, volume=100, nbss=1, pos=.4, sellres=.1, loc=.5),
        _d("3", low=95, close=102, rng=6, value=100, volume=100, nbss=1, pos=.4, sellres=.1, loc=.5),
        _d("4", low=96, close=101, rng=4, value=150, volume=120, nbss=2, pos=.5, sellres=.2, loc=.55),
        _d("5", low=97, close=99, rng=3, value=160, volume=130, nbss=2, pos=.5, sellres=.2, loc=.55),
        _d("6", low=98, close=101, rng=2, value=170, volume=140, nbss=2, pos=.5, sellres=.2, loc=.60),
    ]
    assert "J01_QUIET_MONEY_WAKE_RESPONSE_RETENTION" in v11._preconditions(h)
    assert "J05_HIGHER_LOW_COMPRESSION_EXPANSION" in v11._preconditions(h)


def test_sequence_requires_distinct_stages():
    wake = {"value_wake": True, "volume_wake": True, "flow_wake": True, "path_up": False, "range_expand": False, "accept": False, "accel": False, "path": 0.1}
    response = {"value_wake": True, "volume_wake": True, "flow_wake": True, "path_up": True, "range_expand": True, "accept": True, "accel": True, "path": 0.5}
    retain = {"value_wake": True, "volume_wake": True, "flow_wake": True, "path_up": True, "range_expand": True, "accept": True, "accel": True, "path": 0.6}
    fid = "J01_QUIET_MONEY_WAKE_RESPONSE_RETENTION"
    assert v11._wake(fid, wake)
    assert v11._response(fid, response)
    assert v11._retention(fid, retain, wake_path=0.1, response_path=0.5)
