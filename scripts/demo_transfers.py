"""Experiment 5: local transfers, distributed COMMIT, and distributed ABORT."""

from uuid import uuid4

from scripts.common import (
    balances,
    check,
    check_balances,
    client,
    completed_transfer,
    finish,
    require_decision,
    step,
    title,
    transfer,
)


def main() -> None:
    title(5, "Local and cross-shard transfers")

    with client() as http:
        source, local_destination, remote_destination = "A0922", "A0923", "A1922"

        step("Local transfer: both balances change exactly once")
        before_source, before_destination = balances(http, source, local_destination)
        request_id = uuid4()
        response = transfer(http, source, local_destination, 10, request_id)
        response.raise_for_status()

        replay = transfer(http, source, local_destination, 10, request_id)
        replay.raise_for_status()
        check(response.json() == replay.json(), "Retry returned the original result")
        check_balances(
            http,
            (source, local_destination),
            (before_source - 10, before_destination + 10),
        )

        step("Cross-shard transfer: both participants commit")
        before_source, before_destination = balances(http, source, remote_destination)
        result = completed_transfer(http, source, remote_destination, 5)
        print(f"  Decision: {result['decision']}; status: {result['internal_status']}")
        require_decision(result, "COMMIT")
        check_balances(
            http,
            (source, remote_destination),
            (before_source - 5, before_destination + 5),
        )

        step("Insufficient funds: both participants abort")
        abort_source, abort_destination = "A1924", "A0924"
        before = balances(http, abort_source, abort_destination)
        result = completed_transfer(http, abort_source, abort_destination, before[0] + 1)
        print(f"  Decision: {result['decision']}; status: {result['internal_status']}")
        require_decision(result, "ABORT")
        check(
            any(p["shard"] == "A" and p["prepared"] for p in result["participants"]),
            "Shard A was prepared before Shard B refused",
        )
        check_balances(http, (abort_source, abort_destination), before)

    finish()


if __name__ == "__main__":
    main()
