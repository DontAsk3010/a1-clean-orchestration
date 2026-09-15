from __future__ import annotations

from a1clean.formula_research.telegram_mg_clean_v2_study import (
    CLEAN_PROFILES,
    _profile_matches,
)


def _context(*, activity: float, range_ratio: float, path_delta: float, current_path: float, day_change: float):
    return {
        "activity_ratio": activity,
        "range_ratio": range_ratio,
        "path_delta_pct": path_delta,
        "current_path_pct": current_path,
        "day_change_pct": day_change,
    }


def test_moderate_profile_requires_relative_strength():
    profile = CLEAN_PROFILES["ARP_MOD"]
    assert _profile_matches(
        _context(activity=1.30, range_ratio=1.15, path_delta=0.20, current_path=0.80, day_change=1.20),
        profile,
    )
    assert not _profile_matches(
        _context(activity=1.10, range_ratio=1.15, path_delta=0.20, current_path=0.80, day_change=1.20),
        profile,
    )


def test_fresh_profile_rejects_already_extended_day_and_path():
    profile = CLEAN_PROFILES["ARP_MOD_FRESH2_D3"]
    assert _profile_matches(
        _context(activity=1.40, range_ratio=1.20, path_delta=0.30, current_path=1.50, day_change=2.50),
        profile,
    )
    assert not _profile_matches(
        _context(activity=1.40, range_ratio=1.20, path_delta=0.30, current_path=2.50, day_change=2.50),
        profile,
    )
    assert not _profile_matches(
        _context(activity=1.40, range_ratio=1.20, path_delta=0.30, current_path=1.50, day_change=3.50),
        profile,
    )


def test_profile_requires_positive_current_path():
    profile = CLEAN_PROFILES["ARP_BASE"]
    assert not _profile_matches(
        _context(activity=1.20, range_ratio=1.20, path_delta=0.30, current_path=0.0, day_change=0.5),
        profile,
    )
