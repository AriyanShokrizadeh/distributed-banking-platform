"""Cross-shard experiment counts committed transfers without live services."""

import json
from threading import Lock
from uuid import uuid4

import httpx

from scripts.assignment2 import cross_shard
from tests.common import mock_client


def test_cross_shard_experiment_counts_only_committed_transfers(monkeypatch):
    source, destination = "A0925", "A1925"
    balances = {source: 500, destination: 500}
    decisions = {}
    lock = Lock()

    def handle(request):
        if request.method == "POST":
            transfer = json.loads(request.content)
            decision = "COMMIT" if transfer["source_account"] == source else "ABORT"
            transaction_id = str(uuid4())

            with lock:
                decisions[transaction_id] = decision
                if decision == "COMMIT":
                    balances[transfer["source_account"]] -= transfer["amount_minor"]
                    balances[transfer["destination_account"]] += transfer["amount_minor"]
            return httpx.Response(202, json={"transaction_id": transaction_id})

        if request.url.path.startswith("/v1/transactions/"):
            transaction_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "decision": decisions[transaction_id],
                    "participants": [{"decision_acknowledged": True}] * 2,
                },
            )

        account = request.url.path.split("/")[-2]
        return httpx.Response(200, json={"balance_minor": balances[account]})

    monkeypatch.setattr(cross_shard, "client", lambda: mock_client(handle))
    monkeypatch.setattr(cross_shard, "total_money", lambda: sum(balances.values()))
    cross_shard.main()

    assert balances == {source: 476, destination: 524}
    assert len(decisions) == 16
    assert list(decisions.values()).count("COMMIT") == 8
