from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from a1clean.formula_research.formula_replay import packet_to_formula_bars


def _packet(*, nbss="20", s1="1", s2="0", is_index="0", continuous="1"):
    header = (
        "RAW_OPEN",
        "RAW_HIGH",
        "RAW_LOW",
        "RAW_CLOSE",
        "RAW_VOLUME",
        "RAW_OPENINT_PHYSICAL",
        "RAW_AUX2_PHYSICAL",
        "CLK_REGULAR_SESSION1_FLAG",
        "CLK_REGULAR_SESSION2_FLAG",
        "SYMBOL_IS_INDEX",
        "SYMBOL_CONTINUOUS_QUOTATIONS_FLAG",
    )
    row = {
        "RAW_OPEN": "100",
        "RAW_HIGH": "102",
        "RAW_LOW": "99",
        "RAW_CLOSE": "101",
        "RAW_VOLUME": "1000",
        "RAW_OPENINT_PHYSICAL": nbss,
        "RAW_AUX2_PHYSICAL": "5000000",
        "CLK_REGULAR_SESSION1_FLAG": s1,
        "CLK_REGULAR_SESSION2_FLAG": s2,
        "SYMBOL_IS_INDEX": is_index,
        "SYMBOL_CONTINUOUS_QUOTATIONS_FLAG": continuous,
    }
    return SimpleNamespace(
        header=header,
        rows=(row,),
        timestamps=(datetime(2026, 5, 29, 9, 31),),
        identity=SimpleNamespace(trading_date="2026-05-29"),
    )


def test_current_clean_physical_aux2_openint_mapping_is_bound_exactly():
    bars, mapping = packet_to_formula_bars(_packet())
    assert mapping["trade_value"] == "RAW_AUX2_PHYSICAL"
    assert mapping["nbss"] == "RAW_OPENINT_PHYSICAL"
    assert bars[0]["trade_value"] == 5_000_000
    assert bars[0]["nbss"] == 20
    assert bars[0]["flow_available"] is True
    assert bars[0]["mechanism_eligible"] is True
    assert bars[0]["session_eligible"] is True


def test_session_eligibility_uses_data_plane_flags_not_wall_clock_guess():
    bars, _ = packet_to_formula_bars(_packet(s1="0", s2="0"))
    assert bars[0]["session_eligible"] is False
    assert bars[0]["mechanism_eligible"] is False


def test_index_or_noncontinuous_symbol_is_not_ordinary_formula_mechanism():
    index_bars, _ = packet_to_formula_bars(_packet(is_index="1"))
    noncontinuous_bars, _ = packet_to_formula_bars(_packet(continuous="0"))
    assert index_bars[0]["session_eligible"] is False
    assert noncontinuous_bars[0]["session_eligible"] is False


def test_physical_zero_nbss_remains_unavailable_not_neutral():
    bars, _ = packet_to_formula_bars(_packet(nbss="0"))
    assert bars[0]["nbss"] == 0
    assert bars[0]["flow_available"] is False
    assert bars[0]["mechanism_eligible"] is False
