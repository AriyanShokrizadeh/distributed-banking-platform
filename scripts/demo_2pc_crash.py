"""Experiment 6: crash the Coordinator and recover its durable 2PC decision."""

import argparse
import time
from uuid import UUID, uuid4

import httpx

from scripts.common import (
    balances,
    check,
    check_balances,
    client,
    compose,
    docker,
    finish,
    require_decision,
    sql,
    step,
    title,
    transfer,
    wait_for_transaction,
)

FAULTS = {
    "prepared": ("CRASH_AFTER_PREPARED_ONCE", "PREPARED", "NULL"),
    "commit": ("CRASH_AFTER_COMMIT_ONCE", "COMMIT_DECIDED", "COMMIT"),
}


def restart_coordinator(flag: str, enabled: bool) -> None:
    compose(
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "coordinator",
        env={flag: str(int(enabled))},
    )
    wait_until_healthy()


def wait_until_healthy(timeout: float = 45) -> None:
    container = compose("ps", "-a", "-q", "coordinator")
    if not container:
        raise RuntimeError("Coordinator container not found")

    deadline = time.monotonic() + timeout
    status = "unknown"
    while time.monotonic() < deadline:
        status = docker("inspect", "-f", "{{.State.Health.Status}}", container)
        if status == "healthy":
            return
        time.sleep(0.5)

    raise TimeoutError(f"Coordinator did not become healthy: {status}")


def wait_for_crash(timeout: float = 45) -> None:
    container = compose("ps", "-a", "-q", "coordinator")
    if not container:
        raise RuntimeError("Coordinator container not found")
    deadline = time.monotonic() + timeout
    state = "unknown"
    while time.monotonic() < deadline:
        state = docker("inspect", "-f", "{{.State.Status}}:{{.State.ExitCode}}", container)
        if state == "exited:71":
            return
        time.sleep(0.5)
    raise TimeoutError(f"Coordinator did not crash as expected: {state}")


def send_transfer(http: httpx.Client, source: str, destination: str, amount: int, key: UUID) -> None:
    error = ""
    try:
        response = transfer(http, source, destination, amount, key)
        if response.status_code < 500:
            response.raise_for_status()
            return
        error = f"HTTP {response.status_code}: {response.text}"
    except httpx.RequestError as exc:
        error = str(exc)

    transaction_id = sql(
        "db_coordinator",
        f"SELECT transaction_id FROM distributed_transactions WHERE client_request_id = '{key}'",
    )
    if not transaction_id:
        raise RuntimeError(f"Transfer was not recorded by Coordinator: {error}")
    print(f"  Response interrupted, but transaction {transaction_id} was recorded")


def verify_crash(request_id: str, point: str) -> str:
    _, expected_status, expected_decision = FAULTS[point]
    record = sql(
        "db_coordinator",
        "SELECT transaction_id, status, COALESCE(decision, 'NULL') "
        "FROM distributed_transactions "
        f"WHERE client_request_id = '{request_id}'",
    ).split("|")
    if len(record) != 3 or record[1:] != [expected_status, expected_decision]:
        raise RuntimeError(f"Unexpected durable state: {record}")

    transaction_id = record[0]
    for database in ("db_a", "db_b"):
        prepared = sql(
            database,
            f"SELECT COUNT(*) FROM pg_prepared_xacts WHERE gid LIKE 'bank:%:{transaction_id}:%'",
        )
        check(prepared == "1", f"{database} has its prepared transaction")
    return transaction_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--point", choices=FAULTS, default="commit")
    point = parser.parse_args().point
    flag = FAULTS[point][0]
    source, destination, amount = "A0920", "A1920", 11
    key = uuid4()

    title(6, "Coordinator crash and recovery")
    with client() as http:
        before = balances(http, source, destination)
        sql("db_coordinator", f"DELETE FROM fault_injections WHERE name = '{flag}'")
        try:
            step(f"Arm fault after {point.upper()} and send a transfer")
            restart_coordinator(flag, enabled=True)
            send_transfer(http, source, destination, amount, key)
            wait_for_crash()
            step("Inspect durable state while Coordinator is stopped")
            transaction_id = verify_crash(str(key), point)
            print(f"  Transaction: {transaction_id}")
        finally:
            step("Restart Coordinator with fault injection disabled")
            restart_coordinator(flag, enabled=False)

        result = wait_for_transaction(http, transaction_id, timeout=90)
        print(f"  Recovered decision: {result['decision']}")
        require_decision(result, "COMMIT")
        check_balances(http, (source, destination), (before[0] - amount, before[1] + amount))
        check(result["status"] == "COMPLETED", "Both participants acknowledged COMMIT")

    finish()


if __name__ == "__main__":
    main()
