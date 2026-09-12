from __future__ import annotations

def dtw_distance(a,b):
    """DTW distance only; interpretation/classification remains outside this lane."""
    from tslearn.metrics import dtw
    return float(dtw(a,b))
