from a1clean.formula_research.v31_manual_concordance_extract import _carry_from_packet

def test_carry_from_packet_preserves_previous_day_packet_facts():
    packet = {
        "bars": [
            {"timestamp": "2024-12-02 09:00:00", "close": 100},
            {"timestamp": "2024-12-02 15:49:00", "close": 98},
        ]
    }
    out = _carry_from_packet(packet, "Raw Des 02-31-2024.csv", "2024-12-02")
    assert out["status"] == "EXACT_PREVIOUS_GOVERNED_DATE_PACKET"
    assert out["previous_governed_date"] == "2024-12-02"
    assert out["bar_count"] == 2
    assert out["final_close"] == 98
