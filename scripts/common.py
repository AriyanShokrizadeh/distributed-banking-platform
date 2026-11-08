"""Small, reusable helpers for the banking demos."""

import os
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")


def title(number: int, name: str) -> None:
    print(f"\n{'=' * 56}\nExperiment {number}: {name}\n{'=' * 56}", flush=True)


def step(message: str) -> None:
    print(f"\n> {message}", flush=True)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print(f"  [OK] {message}", flush=True)


def finish() -> None:
    print("\nPASS", flush=True)


def client() -> httpx.Client:
    return httpx.Client(base_url=GATEWAY_URL, timeout=15)


def docker(*args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.check_output(
        ["docker", *args],
        cwd=ROOT,
        text=True,
        env={**os.environ, **(env or {})},
    ).strip()


def compose(*args: str, env: dict[str, str] | None = None) -> str:
    return docker("compose", *args, env=env)


def sql(service: str, statement: str) -> str:
    database = "coordinator" if service == "db_coordinator" else "banking"
    return compose(
        "exec",
        "-T",
        service,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        database,
        "-d",
        database,
        "-tA",
        "-c",
        statement,
    )


def balance(http: httpx.Client, account: str) -> int:
    response = http.get(f"/v1/accounts/{account}/balance")
    response.raise_for_status()
    return int(response.json()["balance_minor"])


def balances(http: httpx.Client, first: str, second: str) -> tuple[int, int]:
    return balance(http, first), balance(http, second)


def check_balances(
    http: httpx.Client,
    accounts: tuple[str, str],
    expected: tuple[int, int],
) -> None:
    actual = balances(http, *accounts)
    for account, value, target in zip(accounts, actual, expected, strict=True):
        print(f"  {account}: {value} (expected {target})")
    check(actual == expected, "Account balances match the expected result")


def post(
    http: httpx.Client,
    path: str,
    data: dict[str, str | int],
    key: UUID | None = None,
) -> httpx.Response:
    request_id = key if key is not None else uuid4()
    return http.post(path, json=data, headers={"Idempotency-Key": str(request_id)})


def transfer(
    http: httpx.Client,
    source: str,
    destination: str,
    amount: int,
    key: UUID | None = None,
) -> httpx.Response:
    payload = {
        "source_account": source,
        "destination_account": destination,
        "amount_minor": amount,
    }
    return post(http, "/v1/transfers", payload, key)


def wait_for_transaction(
    http: httpx.Client,
    transaction_id: str,
    timeout: float = 120,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            response = http.get(f"/v1/transactions/{transaction_id}", timeout=5)
            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                if result["status"] == "COMPLETED":
                    return result
            elif response.status_code not in (502, 503, 504):
                response.raise_for_status()
        except httpx.RequestError:
            pass

        time.sleep(0.5)

    raise TimeoutError(f"Transaction {transaction_id} did not complete")


def completed_transfer(
    http: httpx.Client,
    source: str,
    destination: str,
    amount: int,
    timeout: float = 120,
) -> dict[str, Any]:
    response = transfer(http, source, destination, amount)
    response.raise_for_status()
    return wait_for_transaction(http, response.json()["transaction_id"], timeout)


def require_decision(result: dict[str, Any], decision: str) -> None:
    participants = result["participants"]
    valid = (
        result.get("status", "COMPLETED") == "COMPLETED"
        and result["decision"] == decision
        and len(participants) == 2
        and all(participant["decision_acknowledged"] for participant in participants)
    )
    if not valid:
        raise RuntimeError(f"Incomplete or unexpected {decision}: {result}")


def total_money() -> int:
    statement = "SELECT COALESCE(SUM(balance_minor), 0) FROM accounts"
    return sum(int(sql(shard, statement)) for shard in ("db_a", "db_b"))
