from __future__ import annotations

def segment(signal, *, algorithm: str, model: str, predict_kwargs: dict, algorithm_kwargs: dict | None = None):
    """Run Ruptures with caller-supplied algorithm/model/parameters; no project defaults are invented."""
    import ruptures as rpt
    cls=getattr(rpt,algorithm)
    algo=cls(model=model,**(algorithm_kwargs or {})).fit(signal)
    return algo.predict(**predict_kwargs)
