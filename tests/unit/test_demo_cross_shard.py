"""Exercise cross-shard demo calculations without Docker or PostgreSQL."""

import json
from threading import Lock
from uuid import uuid4

import httpx
import pytest

from scripts import demo_cross_shard


def test_cross_shard_demo_counts_only_committed_transfers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, destination = "A0925", "A1925"
    account_balances = {source: 500, destination: 500}
    decisions: dict[str, str] = {}
    lock = Lock()

    def handle(request: httpx.Request) -> httpx.Response:
        account = request.url.path.split("/")[-2]
        if request.method == "POST":
            payload = json.loads(request.content)
            decision = "COMMIT" if payload["source_account"] == source else "ABORT"
            transaction_id = str(uuid4())
            with lock:
                decisions[transaction_id] = decision
                if decision == "COMMIT":
                    account_balances[payload["source_account"]] -= payload["amount_minor"]
                    account_balances[payload["destination_account"]] += payload["amount_minor"]
            return httpx.Response(202, json={"transaction_id": transaction_id})

        if request.url.path.startswith("/v1/transactions/"):
            transaction_id = request.url.path.split("/")[-1]
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "decision": decisions[transaction_id],
                    "participants": [
                        {"decision_acknowledged": True},
                        {"decision_acknowledged": True},
                    ],
                },
            )

        return httpx.Response(200, json={"balance_minor": account_balances[account]})

    http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))
    monkeypatch.setattr(demo_cross_shard, "client", lambda: http)
    monkeypatch.setattr(demo_cross_shard, "total_money", lambda: sum(account_balances.values()))

    demo_cross_shard.main()

    assert account_balances == {source: 476, destination: 524}
    assert len(decisions) == 16
    assert list(decisions.values()).count("COMMIT") == 8
