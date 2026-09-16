from __future__ import annotations

from a1clean.formula_research.claude_mg_daily_feed_v1 import (
    _preopen_rows,
    _slot_of,
    render_feed_text,
)


def _bar(*, ts, s1=True, s2=False):
    return {"timestamp": ts, "regular_session1": s1, "regular_session2": s2}


def test_bar_minute_is_floored_into_its_five_minute_slot():
    assert _slot_of("2024-12-20 09:00:00", 5) == ("2024-12-20", "09:00")
    assert _slot_of("2024-12-20 09:04:00", 5) == ("2024-12-20", "09:00")
    assert _slot_of("2024-12-20 09:07:00", 5) == ("2024-12-20", "09:05")
    assert _slot_of("2024-12-20 11:29:00", 5) == ("2024-12-20", "11:25")
    assert _slot_of("2024-12-20 13:42:00", 5) == ("2024-12-20", "13:40")


def test_slot_handles_missing_or_malformed_timestamps():
    assert _slot_of(None, 5) is None
    assert _slot_of("2024-12-20", 5) is None
    assert _slot_of("2024-12-20 xx:yy:00", 5) is None


def test_preopen_rows_are_those_before_the_first_regular_bar():
    bars = [
        _bar(ts="2024-12-20 08:45:00", s1=False),
        _bar(ts="2024-12-20 08:55:00", s1=False),
        _bar(ts="2024-12-20 09:00:00", s1=True),
        _bar(ts="2024-12-20 09:05:00", s1=True),
    ]
    pre = _preopen_rows(bars)
    assert len(pre) == 2
    assert pre[0]["timestamp"] == "2024-12-20 08:45:00"


def test_non_regular_rows_after_the_open_are_not_counted_as_preopen():
    bars = [
        _bar(ts="2024-12-20 09:00:00", s1=True),
        _bar(ts="2024-12-20 12:00:00", s1=False),  # midday break, not pre-open
        _bar(ts="2024-12-20 13:30:00", s1=False, s2=True),
    ]
    assert _preopen_rows(bars) == []


def test_day_with_no_regular_bars_reports_no_preopen_rather_than_all_rows():
    bars = [_bar(ts="2024-12-20 08:45:00", s1=False)]
    assert _preopen_rows(bars) == []


def test_rendering_states_when_nothing_was_published():
    text = render_feed_text(
        {"source_name": "X", "slot_minutes": 5, "ticker_count": 0, "days": []},
        from_time="09:00",
        max_rows_per_day=10,
    )
    assert "published nothing" in text


def test_rendering_applies_the_display_filter_without_touching_the_data():
    payload = {
        "source_name": "X",
        "slot_minutes": 5,
        "ticker_count": 1,
        "trading_dates_in_source": 1,
        "trading_dates_with_any_publication": 1,
        "preopen_candidate_rows": {"total_rows": 3, "ticker_days_with_such_rows": 1},
        "days": [
            {
                "date": "2024-12-20",
                "slot_count": 2,
                "unique_ticker_count": 1,
                "unique_tickers": ["AAAA"],
                "slots": [
                    {"slot": "08:50", "ticker_count": 1, "tickers": [{"code": "AAAA", "price": 100.0, "chg_pct": 1.0}]},
                    {"slot": "09:05", "ticker_count": 1, "tickers": [{"code": "BBBB", "price": 200.0, "chg_pct": 2.0}]},
                ],
            }
        ],
    }
    text = render_feed_text(payload, from_time="09:00", max_rows_per_day=10)
    assert "BBBB" in text
    assert "08:50" not in text  # filtered from display only
    assert "pre-open candidate rows in source: 3" in text
