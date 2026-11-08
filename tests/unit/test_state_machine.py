import pytest
from services.coordinator.state_machine import (
    recovery_action,
    assert_decision_not_reversed,
)


@pytest.mark.parametrize(
    "state,decision,action",
    [
        ("INITIATED", None, "PREPARE"),
        ("PREPARING", None, "PREPARE"),
        ("PREPARED", None, "DECIDE_COMMIT"),
        ("COMMIT_DECIDED", "COMMIT", "DRIVE_COMMIT"),
        ("ABORT_DECIDED", "ABORT", "DRIVE_ABORT"),
        ("COMPLETED", "COMMIT", "DONE"),
        ("COMPLETED", "ABORT", "DONE"),
    ],
)
def test_recovery_action(state, decision, action):
    assert recovery_action(state, decision) == action


def test_recovery_rejects_inconsistent_record():
    with pytest.raises(ValueError):
        recovery_action("COMPLETED", None)
    with pytest.raises(ValueError):
        recovery_action("OTHER", None)


def test_decisions_immutable():
    assert_decision_not_reversed(None, "COMMIT")
    assert_decision_not_reversed("COMMIT", "COMMIT")
    with pytest.raises(ValueError):
        assert_decision_not_reversed("COMMIT", "ABORT")
    with pytest.raises(ValueError):
        assert_decision_not_reversed("ABORT", "COMMIT")
    with pytest.raises(ValueError):
        assert_decision_not_reversed(None, "CANCEL")
