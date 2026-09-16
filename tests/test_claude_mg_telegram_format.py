from __future__ import annotations

from a1clean.formula_research.claude_mg_telegram_format import (
    COLUMNS,
    _extract_signals,
    group_by_slot,
    render_feed,
    render_rows,
    render_slot_table,
)


def _signal(ticker, ts, *, price, chg, tp1, tp2):
    return {
        "ticker": ticker,
        "trading_date": ts.split(" ")[0],
        "timestamp": ts,
        "published": {"price": price, "chg_pct": chg, "tp1": tp1, "tp2": tp2},
    }


def test_row_carries_the_five_contract_columns_in_order():
    assert COLUMNS == ("CODE", "PRICE", "CHG%", "TP-1", "TP-2")
    rows = render_rows([_signal("BBCA", "2024-12-10 09:05:00", price=9750.0, chg=1.5625, tp1=9900.0, tp2=10050.0)])
    assert list(rows[0]) == list(COLUMNS)
    assert rows[0]["CODE"] == "BBCA"
    assert rows[0]["CHG%"] == "+1.56%"


def test_negative_change_keeps_its_sign():
    rows = render_rows([_signal("ANTM", "2024-12-10 09:05:00", price=1500.0, chg=-2.5, tp1=1530.0, tp2=1560.0)])
    assert rows[0]["CHG%"] == "-2.50%"


def test_missing_values_render_as_unknown_never_as_zero():
    rows = render_rows([{"ticker": "XXXX", "timestamp": "2024-12-10 09:00:00", "published": {}}])
    assert rows[0]["PRICE"] == "UNKNOWN"
    assert rows[0]["TP-1"] == "UNKNOWN"
    assert rows[0]["CHG%"] == "UNKNOWN"


def test_signals_group_into_chronological_snapshot_slots():
    signals = [
        _signal("CCCC", "2024-12-10 09:10:00", price=100.0, chg=1.0, tp1=101.0, tp2=102.0),
        _signal("AAAA", "2024-12-10 09:00:00", price=200.0, chg=2.0, tp1=202.0, tp2=204.0),
        _signal("BBBB", "2024-12-10 09:00:00", price=300.0, chg=3.0, tp1=303.0, tp2=306.0),
    ]
    grouped = group_by_slot(signals)
    assert list(grouped) == ["2024-12-10 09:00:00", "2024-12-10 09:10:00"]
    assert len(grouped["2024-12-10 09:00:00"]) == 2


def test_slot_table_shows_every_column_header_and_each_ticker():
    table = render_slot_table(
        "2024-12-10 09:00:00",
        [
            _signal("AAAA", "2024-12-10 09:00:00", price=200.0, chg=2.0, tp1=202.0, tp2=204.0),
            _signal("BBBB", "2024-12-10 09:00:00", price=300.0, chg=3.0, tp1=303.0, tp2=306.0),
        ],
    )
    for col in COLUMNS:
        assert col in table
    assert "AAAA" in table and "BBBB" in table
    assert "(2 ticker)" in table


def test_empty_signal_set_says_so_instead_of_printing_an_empty_table():
    assert "published nothing" in render_feed([])


def test_feed_truncation_declares_how_many_slots_were_hidden():
    signals = [
        _signal(f"T{i:03d}", f"2024-12-10 09:{i * 5:02d}:00", price=100.0, chg=1.0, tp1=101.0, tp2=102.0)
        for i in range(6)
    ]
    feed = render_feed(signals, max_slots=2)
    assert "4 further snapshot slot(s) not shown" in feed


def test_extract_reads_either_validation_signals_or_discovery_selected_signals():
    assert _extract_signals({"signals": [{"ticker": "A"}]})[0]["ticker"] == "A"
    assert _extract_signals({"signals_for_selected_thresholds": [{"ticker": "B"}]})[0]["ticker"] == "B"
    assert _extract_signals({"summary": {}}) == []
