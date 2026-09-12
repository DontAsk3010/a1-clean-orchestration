from a1clean.automation_activation import (
    ACTIVATION_AUTH_PHRASE,
    ACTIVATE_CANONICAL_IF_CHANGED,
    VERIFY,
)
from a1clean.post_commit import _snapshot_fingerprint


def test_snapshot_fingerprint_is_order_stable_for_dict_keys():
    left = {"a": 1, "b": {"x": 2, "y": 3}}
    right = {"b": {"y": 3, "x": 2}, "a": 1}
    assert _snapshot_fingerprint(left) == _snapshot_fingerprint(right)


def test_activation_modes_and_authorization_are_explicit():
    assert VERIFY == "VERIFY"
    assert ACTIVATE_CANONICAL_IF_CHANGED == "ACTIVATE_CANONICAL_IF_CHANGED"
    assert ACTIVATION_AUTH_PHRASE == "AUTHORIZE_GOVERNED_AUTOMATION_ACTIVATION"
