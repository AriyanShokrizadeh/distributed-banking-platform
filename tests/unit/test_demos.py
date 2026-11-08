"""Failover demos are safe to test with mocked HTTP and Docker commands."""

import subprocess

import httpx
import pytest

from scripts import demo_2pc_crash, demo_failover


def test_failover_always_restores_stopped_replica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[str] = []
    client = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ready"}),
        ),
    )
    monkeypatch.setattr(demo_failover.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(demo_failover, "compose", actions.append)

    def fail(client: httpx.Client) -> None:
        raise TimeoutError("no failover")

    monkeypatch.setattr(demo_failover, "wait_for_failover", fail)
    with pytest.raises(TimeoutError):
        demo_failover.main()
    assert actions == ["stop", "start"]


def test_failed_stop_does_not_start_replica(monkeypatch: pytest.MonkeyPatch) -> None:
    actions: list[str] = []
    client = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "ready"}),
        ),
    )
    monkeypatch.setattr(demo_failover.httpx, "Client", lambda **kwargs: client)

    def fail(action: str) -> None:
        actions.append(action)
        raise subprocess.CalledProcessError(1, "docker compose stop bank_a1")

    monkeypatch.setattr(demo_failover, "compose", fail)
    with pytest.raises(subprocess.CalledProcessError):
        demo_failover.main()
    assert actions == ["stop"]


def test_crash_demo_validates_persisted_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    txid = "e7475a0f-46dd-4aa4-9021-29c3c9e59423"
    monkeypatch.setattr(
        demo_2pc_crash,
        "sql",
        lambda service, sql: f"{txid}|PREPARED|NULL" if service == "db_coordinator" else "1",
    )
    assert demo_2pc_crash.verify_crash("request", "prepared") == txid
    with pytest.raises(RuntimeError):
        demo_2pc_crash.verify_crash("request", "commit")
