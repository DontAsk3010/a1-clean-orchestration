from a1clean.formula_research.amibroker_parity_compare import compare_rows


def test_parity_passes_for_identical_boolean_states():
    py = [{"Ticker": "A", "DateTime": "2025-01-02 09:15", "P01": True}]
    ami = [{"Ticker": "A", "DateTime": "2025-01-02 09:15", "P01": "1"}]
    result = compare_rows(py, ami, boolean_columns=("P01",))
    assert result["pass"] is True


def test_parity_fails_on_boolean_mismatch():
    py = [{"Ticker": "A", "DateTime": "2025-01-02 09:15", "P01": True}]
    ami = [{"Ticker": "A", "DateTime": "2025-01-02 09:15", "P01": "0"}]
    result = compare_rows(py, ami, boolean_columns=("P01",))
    assert result["pass"] is False
    assert result["boolean_mismatch_count"] == 1


def test_parity_fails_when_row_missing():
    py = [{"Ticker": "A", "DateTime": "2025-01-02 09:15", "P01": True}]
    result = compare_rows(py, [], boolean_columns=("P01",))
    assert result["pass"] is False
    assert result["missing_in_amibroker"]
