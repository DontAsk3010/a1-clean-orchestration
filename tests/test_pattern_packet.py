from __future__ import annotations

import pytest

from a1clean.pattern_discovery.contracts import PatternDiscoveryContractError
from a1clean.pattern_discovery.packet import parse_semantic_packet


def _packet():
    return {
        "generation_id": "GEN",
        "source_drive_id": "SRCID",
        "source_name": "Raw X.csv",
        "source_sha256": "abc",
        "trading_date": "2025-01-02",
        "ticker": "AAAA",
        "first_clock_time": "09:00:00",
        "last_clock_time": "09:02:00",
        "data_row_count": 3,
        "source_row_first": 10,
        "source_row_last": 12,
        "source_row_segments": [[10, 12]],
        "raw_header": "RAW_TICKER,RAW_DATETIME_ISO,RAW_CLOSE,RAW_VOLUME",
        "raw_rows": [
            "AAAA,2025-01-02 09:00:00,100,10",
            "AAAA,2025-01-02 09:01:00,101,20",
            "AAAA,2025-01-02 09:02:00,102,30",
        ],
        "all_source_columns_retained": True,
    }


def test_packet_preserves_exact_row_time_and_source_row_identity():
    packet = parse_semantic_packet(_packet())
    assert packet.row_count == 3
    assert packet.numeric_series("RAW_CLOSE") == (100.0, 101.0, 102.0)
    assert packet.point_ref(1) == {
        "index": 1,
        "source_row": 11,
        "timestamp": "2025-01-02 09:01:00",
        "clock_time": "09:01:00",
    }
    assert packet.range_ref(0, 2)["length"] == 3


def test_packet_rejects_duplicate_or_out_of_order_time():
    obj = _packet()
    obj["raw_rows"][2] = "AAAA,2025-01-02 09:01:00,102,30"
    with pytest.raises(PatternDiscoveryContractError, match="RAW_TIME_DUPLICATE_OR_OUT_OF_ORDER"):
        parse_semantic_packet(obj)


def test_requested_numeric_field_never_interpolates_missing_value():
    obj = _packet()
    obj["raw_rows"][1] = "AAAA,2025-01-02 09:01:00,,20"
    packet = parse_semantic_packet(obj)
    with pytest.raises(PatternDiscoveryContractError, match="REQUESTED_FIELD_MISSING_VALUE"):
        packet.numeric_series("RAW_CLOSE")


def test_packet_rejects_source_row_accounting_mismatch():
    obj = _packet()
    obj["source_row_segments"] = [[10, 11]]
    with pytest.raises(PatternDiscoveryContractError, match="SOURCE_ROW_SEGMENTS_COUNT_MISMATCH"):
        parse_semantic_packet(obj)
