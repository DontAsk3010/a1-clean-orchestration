from __future__ import annotations

import pytest

from a1clean.pattern_discovery.contracts import DiscoveryPlan, PatternDiscoveryContractError


def test_discovery_plan_requires_explicit_algorithmic_parameters():
    with pytest.raises(PatternDiscoveryContractError, match="RUPTURES_PREDICT_KWARGS_REQUIRED"):
        DiscoveryPlan.from_dict(
            {
                "plan_id": "p1",
                "ruptures": [
                    {
                        "run_id": "r1",
                        "field": "RAW_CLOSE",
                        "algorithm": "Pelt",
                        "model": "l2",
                        "predict_kwargs": {},
                    }
                ],
            }
        )


def test_discovery_plan_has_no_hidden_default_window_or_duplicate_run_ids():
    with pytest.raises(PatternDiscoveryContractError, match="STUMPY_SPEC_MISSING"):
        DiscoveryPlan.from_dict(
            {"plan_id": "p1", "stumpy": [{"run_id": "s1", "field": "RAW_CLOSE"}]}
        )

    with pytest.raises(PatternDiscoveryContractError, match="DISCOVERY_RUN_ID_DUPLICATE"):
        DiscoveryPlan.from_dict(
            {
                "plan_id": "p1",
                "stumpy": [{"run_id": "same", "field": "RAW_CLOSE", "window": 5}],
                "dtw": [{"run_id": "same", "left_field": "RAW_CLOSE", "right_field": "RAW_VOLUME"}],
            }
        )


def test_discovery_plan_rejects_unknown_configuration_keys():
    with pytest.raises(PatternDiscoveryContractError, match="DISCOVERY_PLAN_UNKNOWN_KEYS"):
        DiscoveryPlan.from_dict({"plan_id": "p1", "magic_threshold": 0.7})
