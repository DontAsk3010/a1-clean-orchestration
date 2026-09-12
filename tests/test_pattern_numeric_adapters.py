from __future__ import annotations

import sys
import types

from a1clean.pattern_discovery.dtw_tslearn_lane import dtw_distance
from a1clean.pattern_discovery.ruptures_lane import segment
from a1clean.pattern_discovery.stumpy_lane import matrix_profile


class FakeArray(tuple):
    pass


def _install_fake_numpy(monkeypatch, observed):
    def asarray(values, dtype=float):
        observed.setdefault("asarray_calls", []).append({"values": tuple(values), "dtype": dtype})
        return FakeArray(values)

    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(asarray=asarray))


def test_ruptures_adapter_normalizes_tuple_before_library_call(monkeypatch):
    observed = {}
    _install_fake_numpy(monkeypatch, observed)

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

    monkeypatch.setitem(sys.modules, "ruptures", types.SimpleNamespace(Pelt=FakePelt))

    result = segment((1, 2, 3), algorithm="Pelt", model="l2", predict_kwargs={"pen": 1.0})

    assert result == [3]
    assert isinstance(observed["signal"], FakeArray)
    assert observed["asarray_calls"] == [{"values": (1, 2, 3), "dtype": float}]


def test_stumpy_adapter_normalizes_tuple_before_library_call(monkeypatch):
    observed = {}
    _install_fake_numpy(monkeypatch, observed)

    def fake_stump(values, m):
        observed["values"] = values
        observed["m"] = m
        return [[0.0, -1, -1, -1], [0.0, -1, -1, -1]]

    monkeypatch.setitem(sys.modules, "stumpy", types.SimpleNamespace(stump=fake_stump))

    profile = matrix_profile((1, 2, 3, 4), window=3)

    assert len(profile) == 2
    assert isinstance(observed["values"], FakeArray)
    assert observed["m"] == 3
    assert observed["asarray_calls"] == [{"values": (1, 2, 3, 4), "dtype": float}]


def test_dtw_adapter_normalizes_both_tuples_before_library_call(monkeypatch):
    observed = {}
    _install_fake_numpy(monkeypatch, observed)

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
    assert isinstance(observed["left"], FakeArray)
    assert isinstance(observed["right"], FakeArray)
    assert observed["asarray_calls"] == [
        {"values": (1, 2), "dtype": float},
        {"values": (3, 4), "dtype": float},
    ]
