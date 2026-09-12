from __future__ import annotations

import sys
import types

import numpy as np

from a1clean.pattern_discovery.dtw_tslearn_lane import dtw_distance
from a1clean.pattern_discovery.ruptures_lane import segment
from a1clean.pattern_discovery.stumpy_lane import matrix_profile


def test_ruptures_adapter_converts_tuple_to_ndarray(monkeypatch):
    observed = {}

    class FakePelt:
        def __init__(self, model, **kwargs):
            observed["model"] = model
            observed["kwargs"] = kwargs

        def fit(self, signal):
            observed["signal"] = signal
            return self

        def predict(self, **kwargs):
            observed["predict"] = kwargs
            return [3]

    fake = types.SimpleNamespace(Pelt=FakePelt)
    monkeypatch.setitem(sys.modules, "ruptures", fake)

    result = segment((1, 2, 3), algorithm="Pelt", model="l2", predict_kwargs={"pen": 1.0})

    assert result == [3]
    assert isinstance(observed["signal"], np.ndarray)
    assert observed["signal"].dtype.kind == "f"


def test_stumpy_adapter_converts_tuple_to_ndarray(monkeypatch):
    observed = {}

    def fake_stump(values, m):
        observed["values"] = values
        observed["m"] = m
        return np.zeros((2, 4), dtype=float)

    monkeypatch.setitem(sys.modules, "stumpy", types.SimpleNamespace(stump=fake_stump))

    profile = matrix_profile((1, 2, 3, 4), window=3)

    assert profile.shape == (2, 4)
    assert isinstance(observed["values"], np.ndarray)
    assert observed["values"].dtype.kind == "f"
    assert observed["m"] == 3


def test_dtw_adapter_converts_tuples_to_ndarrays(monkeypatch):
    observed = {}

    def fake_dtw(left, right):
        observed["left"] = left
        observed["right"] = right
        return 7.5

    metrics = types.ModuleType("tslearn.metrics")
    metrics.dtw = fake_dtw
    tslearn = types.ModuleType("tslearn")
    tslearn.metrics = metrics
    monkeypatch.setitem(sys.modules, "tslearn", tslearn)
    monkeypatch.setitem(sys.modules, "tslearn.metrics", metrics)

    result = dtw_distance((1, 2), (3, 4))

    assert result == 7.5
    assert isinstance(observed["left"], np.ndarray)
    assert isinstance(observed["right"], np.ndarray)
    assert observed["left"].dtype.kind == "f"
    assert observed["right"].dtype.kind == "f"
