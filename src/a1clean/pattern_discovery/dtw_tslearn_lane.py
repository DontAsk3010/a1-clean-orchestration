from __future__ import annotations


def dtw_distance(a, b):
    """DTW distance only; interpretation/classification remains outside this lane."""
    import numpy as np
    from tslearn.metrics import dtw

    left = np.asarray(a, dtype=float)
    right = np.asarray(b, dtype=float)
    return float(dtw(left, right))
