from __future__ import annotations


def segment(signal, *, algorithm: str, model: str, predict_kwargs: dict, algorithm_kwargs: dict | None = None):
    """Run Ruptures with caller-supplied algorithm/model/parameters; no project defaults are invented."""
    import numpy as np
    import ruptures as rpt

    numeric = np.asarray(signal, dtype=float)
    cls = getattr(rpt, algorithm)
    algo = cls(model=model, **(algorithm_kwargs or {})).fit(numeric)
    return algo.predict(**predict_kwargs)
