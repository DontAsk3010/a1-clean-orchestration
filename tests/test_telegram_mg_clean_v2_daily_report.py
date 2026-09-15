from a1clean.formula_research.telegram_mg_clean_v2_daily_report import _outcome_with_hit_times


def test_outcome_hit_times_excludes_alert_bar_and_records_first_future_hits():
    bars = [
        {"timestamp": "2025-01-02 09:25:00", "high": 110.0, "low": 99.0, "close": 100.0},
        {"timestamp": "2025-01-02 09:26:00", "high": 101.0, "low": 99.5, "close": 100.5},
        {"timestamp": "2025-01-02 09:27:00", "high": 103.0, "low": 100.0, "close": 102.0},
        {"timestamp": "2025-01-02 09:28:00", "high": 105.0, "low": 101.0, "close": 104.0},
    ]
    result = _outcome_with_hit_times(bars, 0, entry=100.0, tp1=103.0, tp2=105.0)
    assert result["result"] == "TP2"
    assert result["tp1_hit_time"] == "2025-01-02 09:27:00"
    assert result["tp2_hit_time"] == "2025-01-02 09:28:00"
    assert result["max_high"] == 105.0


def test_outcome_no_tp_has_null_hit_times():
    bars = [
        {"timestamp": "2025-01-02 09:25:00", "high": 101.0, "low": 99.0, "close": 100.0},
        {"timestamp": "2025-01-02 09:26:00", "high": 101.5, "low": 98.0, "close": 99.0},
    ]
    result = _outcome_with_hit_times(bars, 0, entry=100.0, tp1=103.0, tp2=105.0)
    assert result["result"] == "NO_TP"
    assert result["tp1_hit_time"] is None
    assert result["tp2_hit_time"] is None
