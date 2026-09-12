from __future__ import annotations

def matrix_profile(values, *, window: int):
    """Compute matrix profile for an explicitly supplied subsequence window."""
    import stumpy
    return stumpy.stump(values,m=window)
