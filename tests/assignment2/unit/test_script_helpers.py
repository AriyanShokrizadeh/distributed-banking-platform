"""Shared experiment helpers can be tested without live services."""

from uuid import UUID

import httpx
import pytest

from scripts import common
from scripts.assignment2 import compose as compose_helpers
from tests.common import mock_client


def test_balances_reads_each_requested_account():
    balances = {"A0500": 700, "A1500": 800}

    def handle(request):
        account = request.url.path.split("/")[3]
        return httpx.Response(200, json={"balance_minor": balances[account]})

    with mock_client(handle) as client:
        result = common.balances(client, "A0500", "A1500")

    assert result == (700, 800)


def test_completed_transfer_submits_once_and_polls():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"transaction_id": "tx-1"})
        return httpx.Response(200, json={"status": "COMPLETED", "decision": "COMMIT"})

    with mock_client(handle) as client:
        transaction = common.completed_transfer(client, "A0500", "A1500", 20)

    assert transaction["decision"] == "COMMIT"
    assert [request.method for request in requests] == ["POST", "GET"]
    assert UUID(requests[0].headers["Idempotency-Key"])


def test_require_decision_accepts_acknowledged_commit():
    transaction = {
        "decision": "COMMIT",
        "participants": [
            {"decision_acknowledged": True},
            {"decision_acknowledged": True},
        ],
    }

    common.require_decision(transaction, "COMMIT")


@pytest.mark.parametrize(
    "decision,participants",
    [
        ("ABORT", [{"decision_acknowledged": True}] * 2),
        ("COMMIT", [{"decision_acknowledged": True}, {"decision_acknowledged": False}]),
        ("COMMIT", []),
    ],
)
def test_require_decision_rejects_incorrect_or_unacknowledged_decision(decision, participants):
    transaction = {"decision": "COMMIT", "participants": participants}

    with pytest.raises(RuntimeError):
        common.require_decision(transaction, decision)


def test_compose_uses_project_root_and_given_environment(monkeypatch):
    called = {}

    def fake_check_output(command, **kwargs):
        called.update(command=command, **kwargs)
        return "running\n"

    monkeypatch.setattr(compose_helpers.subprocess, "check_output", fake_check_output)

    assert compose_helpers.compose("ps", env={"TEST_FLAG": "1"}) == "running"
    assert called["command"] == ["docker", "compose", "ps"]
    assert called["cwd"] == compose_helpers.ROOT
    assert called["env"]["TEST_FLAG"] == "1"
