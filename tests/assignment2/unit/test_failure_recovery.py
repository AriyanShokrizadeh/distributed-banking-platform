"""Failure experiments must clean up and validate persisted transactions."""

import subprocess

import httpx
import pytest

from scripts.assignment2 import coordinator_failure, replica_failure
from tests.common import mock_client


@pytest.fixture
def failover_client(monkeypatch):
    client = mock_client(lambda _request: httpx.Response(200, json={"status": "ready"}))
    monkeypatch.setattr(replica_failure.httpx, "Client", lambda **_kwargs: client)
    yield client
    client.close()


def test_replica_is_restarted_when_failover_fails(monkeypatch, failover_client):
    actions = []
    monkeypatch.setattr(replica_failure, "compose", actions.append)

    def fail(_client):
        raise TimeoutError("no failover")

    monkeypatch.setattr(replica_failure, "wait_for_failover", fail)

    with pytest.raises(TimeoutError):
        replica_failure.main()

    assert actions == ["stop", "start"]


def test_replica_is_not_started_if_stop_failed(monkeypatch, failover_client):
    actions = []

    def fail_stop(action):
        actions.append(action)
        raise subprocess.CalledProcessError(1, "docker compose stop bank_a1")

    monkeypatch.setattr(replica_failure, "compose", fail_stop)

    with pytest.raises(subprocess.CalledProcessError):
        replica_failure.main()

    assert actions == ["stop"]


def test_coordinator_crash_checks_persisted_transaction_phase(monkeypatch):
    transaction_id = "e7475a0f-46dd-4aa4-9021-29c3c9e59423"

    def fake_sql(service, _query):
        return f"{transaction_id}|PREPARED|NULL" if service == "db_coordinator" else "1"

    monkeypatch.setattr(coordinator_failure, "sql", fake_sql)

    assert coordinator_failure.verify_crash("request", "prepared") == transaction_id
    with pytest.raises(RuntimeError):
        coordinator_failure.verify_crash("request", "commit")
