from a1clean.formula_research.telegram_mg_sequence_discovery_v4 import (
    _sig_id,
    sequence_markers,
)


def test_sequence_markers_distinguish_new_held_and_regain():
    prior = [
        {"FLOW": True, "FRESH": True, "VALUE": False, "RETAINED": False, "RECOVERY": True},
        {"FLOW": False, "FRESH": True, "VALUE": True, "RETAINED": True, "RECOVERY": False},
    ]
    current = {
        "FLOW": True,
        "FRESH": True,
        "VALUE": True,
        "RETAINED": True,
        "RECOVERY": False,
        "PULLBACK": False,
        "RECLAIM": False,
        "RENEWED_HIGH": True,
        "WAKE_ACTIVITY": True,
        "WAKE_RANGE": False,
        "WAKE_PATH": True,
    }
    markers = set(sequence_markers(current, prior))
    assert "NEW_FLOW" in markers
    assert "REGAIN_FLOW" in markers
    assert "HELD_FRESH" in markers
    assert "HELD2_FRESH" in markers
    assert "HELD_VALUE" in markers
    assert "HELD_RETAINED" in markers
    assert "PRIOR3_RECOVERY" in markers
    assert "WAKE_ACTIVITY" in markers
    assert "WAKE_PATH" in markers
    assert "WAKE_RANGE" not in markers


def test_sequence_markers_use_only_prior_publications():
    current = {
        "FLOW": True,
        "FRESH": True,
        "VALUE": True,
        "RETAINED": True,
        "RECOVERY": False,
        "PULLBACK": False,
        "RECLAIM": False,
        "RENEWED_HIGH": False,
        "WAKE_ACTIVITY": False,
        "WAKE_RANGE": False,
        "WAKE_PATH": True,
    }
    markers = set(sequence_markers(current, []))
    assert "NEW_FLOW" in markers
    assert "NEW_FRESH" in markers
    assert "NEW_VALUE" in markers
    assert "NEW_RETAINED" in markers
    assert not any(x.startswith("PREV_") for x in markers)
    assert not any(x.startswith("HELD_") for x in markers)


def test_signature_id_is_order_independent():
    assert _sig_id(("NEW_FLOW", "PRIOR3_RECOVERY")) == _sig_id(("PRIOR3_RECOVERY", "NEW_FLOW"))
