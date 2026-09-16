from types import SimpleNamespace

from a1clean.formula_research.telegram_mg_streaming_multilogic_v9 import (
    _ignition_states,
    _precursor_states,
    _suffix_extremes,
)


def _d(close, low, rng, ret, value, volume, nbss=1.0):
    return SimpleNamespace(
        close=float(close), low=float(low), range_pct=float(rng), return_pct=float(ret),
        value=float(value), volume=float(volume), nbss=float(nbss),
    )


def test_precursor_value_build_and_compression():
    h = [
        _d(100, 98, 5, 2, 10, 10),
        _d(104, 99, 5, 4, 10, 10),
        _d(101, 98, 5, -3, 10, 10),
        _d(101, 100, 2, 0, 20, 20),
        _d(102, 100, 2, 1, 22, 22),
        _d(101.5, 100, 1.5, -0.5, 25, 25),
    ]
    s = _precursor_states(h)
    assert "P_BASE_CONTRACTION_3V3" in s
    assert "P_RANGE_COMPRESSION_3V3" in s
    assert "P_VALUE_BUILD_CONTAINED" in s
    assert "P_VOLUME_BUILD_CONTAINED" in s


def test_ignition_relative_to_historical_same_time():
    current = [{"cur_value": 200.0, "cur_volume": 200.0, "cur_range_pct": 4.0,
                "cur_path_pct": 3.0, "cur_close_location": 0.9,
                "cur_value_accel_5v5": 2.0, "cur_volume_accel_5v5": 2.0,
                "cur_nbss_to_value": 0.2}]
    hist = [[{"cur_value": 100.0, "cur_volume": 100.0, "cur_range_pct": 2.0,
              "cur_path_pct": 1.0, "cur_close_location": 0.6,
              "cur_value_accel_5v5": 1.0, "cur_volume_accel_5v5": 1.0,
              "cur_nbss_to_value": 0.1}]
            for _ in range(3)]
    s = _ignition_states(current, hist, 0)
    assert "I_FULL_CROWD_EXPANSION" in s
    assert "I_FLOW_VALUE_PATH" in s


def test_suffix_extremes():
    bars = [
        {"high": 10, "low": 8, "close": 9},
        {"high": 12, "low": 7, "close": 11},
        {"high": 11, "low": 9, "close": 10},
    ]
    hi, lo, close = _suffix_extremes(bars)
    assert hi[0] == 12
    assert hi[2] == 11
    assert lo[0] == 7
    assert lo[2] == 9
    assert close == 10
