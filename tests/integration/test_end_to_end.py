"""Integration tests for sharding, idempotency and distributed transactions."""

import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

pytestmark = pytest.mark.integration
BASE_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 to run integration tests")

    with httpx.Client(base_url=BASE_URL, timeout=30) as session:
        assert session.get("/health/ready", timeout=4).status_code == 200
        yield session


def balance(client: httpx.Client, account: str) -> int:
    response = client.get(f"/v1/accounts/{account}/balance")
    response.raise_for_status()
    return response.json()["balance_minor"]


def post(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
    key: UUID | None = None,
) -> httpx.Response:
    return client.post(
        path,
        json=payload,
        headers={"Idempotency-Key": str(key or uuid4())},
    )


def parallel_posts(
    client: httpx.Client,
    path: str,
    amount: int,
    count: int,
    workers: int,
) -> list[httpx.Response]:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda _: post(client, path, {"amount_minor": amount}),
                range(count),
            )
        )


def transfer(
    client: httpx.Client,
    source: str,
    destination: str,
    amount: int,
    key: UUID | None = None,
) -> httpx.Response:
    return post(
        client,
        "/v1/transfers",
        {
            "source_account": source,
            "destination_account": destination,
            "amount_minor": amount,
        },
        key,
    )


def submit_cross(
    client: httpx.Client,
    source: str,
    destination: str,
    amount: int,
    key: UUID | None = None,
) -> dict[str, Any]:
    response = transfer(client, source, destination, amount, key)
    assert response.status_code in (200, 202), response.text
    return response.json()


def wait_for_tx(
    client: httpx.Client,
    txid: str,
    timeout: float = 45,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        response = client.get(f"/v1/transactions/{txid}", timeout=5)

        if response.status_code == 200:
            state = response.json()
            if state["status"] == "COMPLETED":
                return state

        time.sleep(0.25)

    pytest.fail(f"Transaction {txid} did not complete within {timeout}s")


def test_shard_routing_and_round_robin(client: httpx.Client) -> None:
    for account, shard, replicas in (
        ("A0500", "A", {"A1", "A2"}),
        ("A1500", "B", {"B1", "B2"}),
    ):
        responses = [client.get(f"/v1/accounts/{account}/balance") for _ in range(8)]

        assert all(r.status_code == 200 for r in responses)
        assert {r.headers["x-shard-id"] for r in responses} == {shard}
        assert {r.headers["x-replica-id"] for r in responses} == replicas


def test_idempotency_across_replicas(client: httpx.Client) -> None:
    account = "A0911"
    path = f"/v1/accounts/{account}/deposits"
    before = balance(client, account)
    key = uuid4()

    first = post(client, path, {"amount_minor": 12}, key)
    replay = post(client, path, {"amount_minor": 12}, key)

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert balance(client, account) == before + 12

    conflict = post(client, path, {"amount_minor": 14}, key)
    assert conflict.status_code == 409


def test_concurrent_deposits(client: httpx.Client) -> None:
    account = "A0912"
    before = balance(client, account)

    responses = parallel_posts(
        client,
        f"/v1/accounts/{account}/deposits",
        amount=3,
        count=24,
        workers=12,
    )

    assert all(r.status_code == 200 for r in responses)
    assert balance(client, account) == before + 72


def test_concurrent_withdrawals(client: httpx.Client) -> None:
    account = "A0913"
    before = balance(client, account)

    responses = parallel_posts(
        client,
        f"/v1/accounts/{account}/withdrawals",
        amount=7,
        count=20,
        workers=10,
    )

    accepted = sum(r.status_code == 200 for r in responses)

    assert all(r.status_code in (200, 409) for r in responses)
    assert balance(client, account) == before - accepted * 7
    assert balance(client, account) >= 0


def test_local_transfer(client: httpx.Client) -> None:
    source, destination = "A0914", "A0915"
    total = balance(client, source) + balance(client, destination)
    key = uuid4()

    first = transfer(client, source, destination, 60, key)
    replay = transfer(client, source, destination, 60, key)

    assert first.status_code == replay.status_code == 200
    assert first.json()["decision"] == "COMMIT"
    assert first.json() == replay.json()
    assert balance(client, source) + balance(client, destination) == total


def test_cross_shard_commit_and_replay(client: httpx.Client) -> None:
    source, destination = "A0916", "A1916"
    before_source = balance(client, source)
    before_destination = balance(client, destination)
    key = uuid4()

    first = submit_cross(client, source, destination, 20, key)
    resolved = wait_for_tx(client, first["transaction_id"])

    assert resolved["decision"] == "COMMIT"
    assert all(p["prepared"] and p["decision_acknowledged"] for p in resolved["participants"])
    assert balance(client, source) == before_source - 20
    assert balance(client, destination) == before_destination + 20

    replay = submit_cross(client, source, destination, 20, key)
    assert replay["transaction_id"] == first["transaction_id"]
    assert balance(client, source) == before_source - 20
    assert balance(client, destination) == before_destination + 20

    conflict = transfer(client, source, destination, 21, key)
    assert conflict.status_code == 409


def test_cross_shard_abort(client: httpx.Client) -> None:
    source, destination = "A1917", "A0917"
    before_source = balance(client, source)
    before_destination = balance(client, destination)

    submitted = submit_cross(
        client,
        source,
        destination,
        before_source + 1,
    )
    resolved = wait_for_tx(client, submitted["transaction_id"])

    assert resolved["decision"] == "ABORT"
    assert resolved["participants"][0]["prepared"] is True
    assert all(p["decision_acknowledged"] for p in resolved["participants"])
    assert balance(client, source) == before_source
    assert balance(client, destination) == before_destination


def test_concurrent_cross_shard_transfers(client: httpx.Client) -> None:
    source, destination = "A0918", "A1918"
    before_source = balance(client, source)
    before_destination = balance(client, destination)

    jobs = [(source, destination, 3)] * 6 + [(destination, source, 2)] * 6

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(submit_cross, client, *job) for job in jobs]
        submitted = [future.result() for future in futures]

    resolved = [wait_for_tx(client, tx["transaction_id"], timeout=100) for tx in submitted]

    assert all(tx["decision"] == "COMMIT" for tx in resolved)
    assert balance(client, source) == before_source - 6 * 3 + 6 * 2
    assert balance(client, destination) == before_destination + 6 * 3 - 6 * 2
    assert balance(client, source) + balance(client, destination) == (before_source + before_destination)
