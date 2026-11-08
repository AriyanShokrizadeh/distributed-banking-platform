"""Tests for shared demo helpers without a running server or Docker."""

from uuid import UUID

import httpx
import pytest

from scripts import common


def test_balances_reads_all_accounts() -> None:
    values = {"A0500": 700, "A1500": 800}

    def handle(request: httpx.Request) -> httpx.Response:
        account = request.url.path.split("/")[3]
        return httpx.Response(200, json={"balance_minor": values[account]})

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as http:
        assert common.balances(http, "A0500", "A1500") == (700, 800)


def test_completed_transfer_uses_unique_id_and_polls() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"transaction_id": "tx-1"})
        return httpx.Response(200, json={"status": "COMPLETED", "decision": "COMMIT"})

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle)) as http:
        result = common.completed_transfer(http, "A0500", "A1500", 20)

    assert result["decision"] == "COMMIT"
    assert [request.method for request in requests] == ["POST", "GET"]
    UUID(requests[0].headers["Idempotency-Key"])


def test_require_decision_checks_both_participants() -> None:
    transaction = {
        "decision": "COMMIT",
        "participants": [
            {"decision_acknowledged": True},
            {"decision_acknowledged": True},
        ],
    }
    common.require_decision(transaction, "COMMIT")
    with pytest.raises(RuntimeError):
        common.require_decision(transaction, "ABORT")
    transaction["participants"][1]["decision_acknowledged"] = False
    with pytest.raises(RuntimeError):
        common.require_decision(transaction, "COMMIT")
    transaction["participants"] = []
    with pytest.raises(RuntimeError):
        common.require_decision(transaction, "COMMIT")


def test_compose_runs_in_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict = {}

    def fake_output(command: list[str], **kwargs) -> str:
        called.update(command=command, **kwargs)
        return "running\n"

    monkeypatch.setattr(common.subprocess, "check_output", fake_output)
    assert common.compose("ps", env={"TEST_FLAG": "1"}) == "running"
    assert called["command"] == ["docker", "compose", "ps"]
    assert called["cwd"] == common.ROOT
    assert called["env"]["TEST_FLAG"] == "1"
