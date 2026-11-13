"""Experiment commands use mocked HTTP instead of real services."""

import sys
from uuid import UUID

import httpx
import pytest

from scripts import common
from scripts.assignment2 import replica_routing, sharding
from tests.common import mock_client


def test_post_generates_idempotency_key_and_preserves_explicit_key():
    keys = []

    def handle(request):
        keys.append(request.headers["Idempotency-Key"])
        return httpx.Response(200, json={"ok": True})

    explicit_key = UUID("81cd7af0-7e53-45c8-a82b-55173d5e2ca9")
    with mock_client(handle) as client:
        common.post(client, "/v1/accounts/A0500/deposits", {"amount_minor": 5})
        common.post(client, "/v1/accounts/A0500/deposits", {"amount_minor": 5}, explicit_key)

    assert str(UUID(keys[0])) == keys[0]
    assert keys[1] == str(explicit_key)


def test_wait_for_transaction_polls_until_completed(monkeypatch):
    calls = 0

    def handle(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "status": "PENDING" if calls == 1 else "COMPLETED",
                "decision": "COMMIT",
            },
        )

    monkeypatch.setattr(common.time, "sleep", lambda _seconds: None)
    with mock_client(handle) as client:
        transaction = common.wait_for_transaction(client, "tx-1")

    assert calls == 2
    assert transaction["decision"] == "COMMIT"


def test_sharding_experiment_checks_both_shard_boundaries(monkeypatch):
    visited = []

    def handle(request):
        account = request.url.path.split("/")[3]
        visited.append(account)
        shard = "A" if int(account[1:]) <= 1000 else "B"
        return httpx.Response(
            200,
            json={"balance_minor": 1000},
            headers={"X-Shard-ID": shard, "X-Replica-ID": f"{shard}1"},
        )

    def database_summary(shard):
        return 1000, f"A{shard['start']:04d}", f"A{shard['end']:04d}", 0

    monkeypatch.setattr(sharding, "database_summary", database_summary)
    monkeypatch.setattr(sharding, "client", lambda: mock_client(handle))

    sharding.main()

    assert visited == ["A0001", "A1000", "A1001", "A2000"]


@pytest.mark.parametrize("both_replicas,request_count", [(False, 4), (True, 6)])
def test_replica_experiment_requires_both_replicas(monkeypatch, both_replicas, request_count):
    calls = 0

    def handle(_request):
        nonlocal calls
        calls += 1
        replica = "A2" if both_replicas and calls % 2 == 0 else "A1"
        return httpx.Response(200, json={"balance_minor": 1000}, headers={"X-Replica-ID": replica})

    monkeypatch.setattr(sys, "argv", ["replica_routing.py", "--requests", str(request_count)])
    monkeypatch.setattr(replica_routing, "client", lambda: mock_client(handle))

    if both_replicas:
        replica_routing.main()
    else:
        with pytest.raises(RuntimeError, match="Requests reached both replicas"):
            replica_routing.main()

    assert calls == request_count
