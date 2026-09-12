from __future__ import annotations

from types import SimpleNamespace

import pytest

from a1clean.pattern_discovery.contracts import PatternDiscoveryContractError
from a1clean.pattern_discovery.runner import (
    _normalize_scope,
    _resolve_manifest_indices,
    _selected_ref,
)


class _Row:
    def __init__(self, trading_date: str, ticker: str, data_row_count: int):
        self.trading_date = trading_date
        self.ticker = ticker
        self.data_row_count = data_row_count

    def as_dict(self):
        return {
            "trading_date": self.trading_date,
            "ticker": self.ticker,
            "data_row_count": self.data_row_count,
        }


def _reader():
    return SimpleNamespace(
        semantic_manifest_rows=(
            _Row("2024-12-02", "AALI", 104),
            _Row("2024-12-02", "ABBA", 6),
            _Row("2024-12-03", "AALI", 98),
        )
    )


def test_full_source_scope_preserves_all_manifest_indices():
    scope = _normalize_scope(trading_date=None, ticker=None)
    assert scope == {"scope_type": "FULL_SOURCE"}
    assert _resolve_manifest_indices(_reader(), scope) == (0, 1, 2)


def test_exact_ticker_day_scope_resolves_one_governed_manifest_row():
    scope = _normalize_scope(trading_date="2024-12-02", ticker="AALI")
    indices = _resolve_manifest_indices(_reader(), scope)
    assert indices == (0,)
    assert _selected_ref(_reader(), indices, 0) == {
        "selection_position": 0,
        "manifest_index": 0,
        "trading_date": "2024-12-02",
        "ticker": "AALI",
        "data_row_count": 104,
    }
    assert _selected_ref(_reader(), indices, 1) is None


@pytest.mark.parametrize(
    ("trading_date", "ticker"),
    [
        ("2024-12-02", None),
        (None, "AALI"),
        ("", "AALI"),
    ],
)
def test_exact_scope_requires_both_identity_fields(trading_date, ticker):
    with pytest.raises(PatternDiscoveryContractError, match="EXACT_SCOPE_REQUIRES_TRADING_DATE_AND_TICKER"):
        _normalize_scope(trading_date=trading_date, ticker=ticker)


def test_exact_scope_fails_closed_when_manifest_identity_is_not_unique_or_missing():
    reader = _reader()
    missing = _normalize_scope(trading_date="2024-12-04", ticker="AALI")
    with pytest.raises(PatternDiscoveryContractError, match="COUNT=0"):
        _resolve_manifest_indices(reader, missing)

    duplicate_reader = SimpleNamespace(
        semantic_manifest_rows=(
            _Row("2024-12-02", "AALI", 104),
            _Row("2024-12-02", "AALI", 104),
        )
    )
    exact = _normalize_scope(trading_date="2024-12-02", ticker="AALI")
    with pytest.raises(PatternDiscoveryContractError, match="COUNT=2"):
        _resolve_manifest_indices(duplicate_reader, exact)
