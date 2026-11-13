"""Recovery decisions are deterministic and irreversible."""

import pytest

from services.coordinator.state_machine import (
    assert_decision_not_reversed,
    recovery_action,
)


@pytest.mark.parametrize(
    "status,decision,expected",
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
def test_recovery_action_for_known_state(status, decision, expected):
    assert recovery_action(status, decision) == expected


@pytest.mark.parametrize("status", ["COMPLETED", "UNKNOWN"])
def test_recovery_rejects_invalid_undecided_state(status):
    with pytest.raises(ValueError):
        recovery_action(status, None)


@pytest.mark.parametrize("existing,requested", [(None, "COMMIT"), ("COMMIT", "COMMIT")])
def test_valid_decision_is_accepted(existing, requested):
    assert_decision_not_reversed(existing, requested)


@pytest.mark.parametrize(
    "existing,requested",
    [("COMMIT", "ABORT"), ("ABORT", "COMMIT"), (None, "CANCEL")],
)
def test_decision_cannot_be_reversed_or_invalid(existing, requested):
    with pytest.raises(ValueError):
        assert_decision_not_reversed(existing, requested)
