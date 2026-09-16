from a1clean.formula_research.telegram_mg_question_driven_v10 import DayBehavior, _question_states, QUESTIONS, IGNITIONS


def d(i, ret, rng, value, volume, nbss, pos, absorb, sellres, late, low, high, close, loc):
    return DayBehavior(
        date=f"2025-01-{i:02d}", open=100.0, high=high, low=low, close=close,
        ret_pct=ret, range_pct=rng, close_location=loc, value=value, volume=volume,
        nbss=nbss, positive_nbss_bar_fraction=pos, negative_nbss_bar_fraction=1-pos,
        down_bar_positive_nbss_fraction=absorb, sell_pressure_resilience_fraction=sellres,
        buy_effort_no_progress_fraction=absorb, late_nbss_to_value=late,
    )


def test_question_space_size():
    assert len(QUESTIONS) == 16
    assert len(IGNITIONS) == 7
    assert len(QUESTIONS) * len(IGNITIONS) == 112


def test_down_but_buyers_stay_and_absorption_questions():
    h = [
        d(1, 1.0, 5.0, 100, 100, -10, .35, .10, .05, -.10, 95,105,101,.60),
        d(2, .5, 5.0, 100, 100, -5, .40, .12, .06, -.05, 96,106,101,.55),
        d(3, .2, 4.5, 100, 100, 0, .42, .15, .07, 0.0, 97,106,101,.50),
        d(4, -.8, 4.0, 130, 120, 5, .55, .25, .12, .05, 96,104,99,.55),
        d(5, -.5, 3.5, 140, 130, 10, .60, .30, .14, .08, 96,103,99,.60),
        d(6, -.2, 3.0, 150, 140, 15, .65, .35, .16, .10, 97,103,100,.65),
    ]
    q = _question_states(h)
    assert "Q01_PRICE_DOWN_BUYERS_STAY" in q
    assert "Q02_PRICE_DOWN_NBSS_IMPROVES" in q
    assert "Q03_PRICE_DOWN_VALUE_ABSORBED" in q
    assert "Q12_ABSORPTION_MINUTES_RISE_BEFORE_PRICE" in q


def test_sideways_money_and_flow_build_questions():
    h = [
        d(1, 1.5, 6.0, 100,100,-5,.40,.10,.05,-.05,95,106,102,.60),
        d(2, 1.0, 5.5, 100,100,-3,.42,.11,.06,-.03,96,106,102,.58),
        d(3, .8, 5.0, 100,100,0,.45,.12,.07,0,97,106,102,.55),
        d(4, .3, 3.0, 140,130,5,.55,.20,.10,.04,99,104,102,.60),
        d(5, .2, 2.8, 150,140,8,.60,.22,.11,.06,100,104,102,.62),
        d(6, .1, 2.5, 160,150,10,.65,.25,.12,.08,101,104,102,.64),
    ]
    q = _question_states(h)
    assert "Q06_SIDEWAYS_MONEY_BUILDS" in q
    assert "Q07_SIDEWAYS_VOLUME_BUILDS" in q
    assert "Q08_SIDEWAYS_BUY_FLOW_BUILDS" in q
