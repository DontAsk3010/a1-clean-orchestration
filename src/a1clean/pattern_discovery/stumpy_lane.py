from __future__ import annotations


def matrix_profile(values, *, window: int):
    """Compute matrix profile for an explicitly supplied subsequence window."""
    import numpy as np
    import stumpy

    numeric = np.asarray(values, dtype=float)
    return stumpy.stump(numeric, m=window)
