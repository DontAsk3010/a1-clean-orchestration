from a1clean.formula_research.dual_lane_behavior_v1 import (
    DualSequenceState,
    _advance,
)


def _snap(
    *,
    ts: str,
    relationship: str,
    path: float,
    constructive: bool,
    active: bool,
    value_wake: bool = False,
    volume_wake: bool = False,
    flow_wake: bool = False,
    flow_available: bool = True,
    buy_flow: bool = False,
    sell_flow: bool = False,
    persists: bool = False,
    collapses: bool = False,
    giveback: bool = False,
    fresh_high: bool = False,
    openlow: bool = False,
    low_stable: bool = True,
    sell_resilience: bool = False,
):
    return {
        "timestamp": ts,
        "relationship": relationship,
        "sell_pressure_resilience": sell_resilience,
        "price": {
            "path": path,
            "constructive": constructive,
            "progress_vs_prev_pub": not giveback,
            "hold_vs_prev_pub": not giveback,
            "giveback_vs_prev_pub": giveback,
            "fresh_running_high": fresh_high,
            "open_is_running_low": openlow,
            "low_stabilized_vs_prev_pub": low_stable,
        },
        "formation": {
            "active": active,
            "activity_active": value_wake or volume_wake,
            "value_wake": value_wake,
            "volume_wake": volume_wake,
            "flow_wake": flow_wake,
            "accel": False,
            "persists": persists,
            "collapses": collapses,
            "flow_available": flow_available,
            "buy_flow": buy_flow,
            "sell_flow": sell_flow,
        },
    }


def test_effort_no_response_then_efficiency_flip_requires_both_lanes():
    st = DualSequenceState()
    assert not _advance("DL03_EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP", st, _snap(
        ts="09:00", relationship="FORMATION_LEADS", path=0.1, constructive=False,
        active=True, value_wake=True,
    ), 0)
    assert st.stage == 1
    assert not _advance("DL03_EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP", st, _snap(
        ts="09:05", relationship="FORMATION_LEADS", path=0.1, constructive=False,
        active=True, value_wake=True, persists=True,
    ), 1)
    assert st.stage == 2
    assert not _advance("DL03_EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP", st, _snap(
        ts="09:10", relationship="ALIGNED_EXPANSION", path=0.5, constructive=True,
        active=True, value_wake=True, persists=True,
    ), 2)
    assert st.stage == 3
    assert _advance("DL03_EFFORT_NO_RESPONSE_THEN_EFFICIENCY_FLIP", st, _snap(
        ts="09:15", relationship="ALIGNED_EXPANSION", path=0.7, constructive=True,
        active=True, value_wake=True, persists=True,
    ), 3)
    assert st.completed


def test_open_low_candidate_invalidates_if_open_breaks_before_reclaim():
    st = DualSequenceState()
    assert not _advance("DL06_OPEN_LOW_DEFEND_RECLAIM_FORMATION", st, _snap(
        ts="09:00", relationship="ALIGNED_EXPANSION", path=1.0, constructive=True,
        active=True, value_wake=True, openlow=True,
    ), 0)
    assert st.stage == 1
    assert not _advance("DL06_OPEN_LOW_DEFEND_RECLAIM_FORMATION", st, _snap(
        ts="09:05", relationship="FORMATION_LEADS", path=0.5, constructive=False,
        active=True, value_wake=True, giveback=True, openlow=True,
    ), 1)
    assert st.stage == 2
    assert not _advance("DL06_OPEN_LOW_DEFEND_RECLAIM_FORMATION", st, _snap(
        ts="09:10", relationship="BOTH_QUIET_OR_UNCONFIRMED", path=0.2, constructive=False,
        active=False, openlow=False,
    ), 2)
    assert st.invalidated
    assert st.invalidation_reason == "OPEN_BROKEN_BEFORE_RECLAIM"


def test_price_lead_requires_formation_confirmation_and_retest():
    st = DualSequenceState()
    assert not _advance("DL02_PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL", st, _snap(
        ts="09:00", relationship="PRICE_LEADS", path=0.4, constructive=True,
        active=False,
    ), 0)
    assert not _advance("DL02_PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL", st, _snap(
        ts="09:05", relationship="ALIGNED_EXPANSION", path=0.8, constructive=True,
        active=True, value_wake=True,
    ), 1)
    assert not _advance("DL02_PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL", st, _snap(
        ts="09:10", relationship="FORMATION_LEADS", path=0.6, constructive=False,
        active=True, value_wake=True, giveback=True,
    ), 2)
    assert st.stage == 3
    assert _advance("DL02_PRICE_LEADS_FORMATION_CONFIRM_RETEST_REACCEL", st, _snap(
        ts="09:15", relationship="ALIGNED_EXPANSION", path=1.0, constructive=True,
        active=True, value_wake=True,
    ), 3)
    assert st.completed
