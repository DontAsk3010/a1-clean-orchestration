import inspect
from a1clean.pattern_discovery import ruptures_lane,stumpy_lane,dtw_tslearn_lane

def test_no_project_analytical_defaults():
    assert inspect.signature(ruptures_lane.segment).parameters["algorithm"].default is inspect._empty
    assert inspect.signature(ruptures_lane.segment).parameters["model"].default is inspect._empty
    assert inspect.signature(stumpy_lane.matrix_profile).parameters["window"].default is inspect._empty
    assert callable(dtw_tslearn_lane.dtw_distance)
