"""Experiment 7: concurrent cross-shard transfers conserve money."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from scripts.common import (
    balances,
    check,
    client,
    finish,
    require_decision,
    step,
    title,
    total_money,
    transfer,
    wait_for_transaction,
)


def main() -> None:
    title(7, "Concurrent cross-shard transfers")

    source, destination = "A0925", "A1925"
    transfers = [(source, destination, 3)] * 8 + [(destination, source, 2)] * 8

    with client() as http:
        before = balances(http, source, destination)
        total_before = total_money()

        def send(job: tuple[str, str, int]) -> str:
            from_account, to_account, amount = job
            response = transfer(http, from_account, to_account, amount)
            response.raise_for_status()
            return str(response.json()["transaction_id"])

        step(f"Send {len(transfers)} transfers concurrently in both directions")
        with ThreadPoolExecutor(max_workers=8) as pool:
            transaction_ids = list(pool.map(send, transfers))

        step("Wait for every 2PC transaction to finish")
        results = [wait_for_transaction(http, txid, timeout=180) for txid in transaction_ids]
        decisions = Counter(result["decision"] for result in results)

        expected: dict[str, int] = {
            source: before[0],
            destination: before[1],
        }
        for (from_account, to_account, amount), result in zip(transfers, results, strict=True):
            require_decision(result, result["decision"])
            if result["decision"] == "COMMIT":
                expected[from_account] -= amount
                expected[to_account] += amount

        after = balances(http, source, destination)
        expected_balances = (expected[source], expected[destination])

        print(f"  Decisions: {dict(decisions)}")
        print(f"  Before: {before}; after: {after}")
        print(f"  Expected: {expected_balances}")

        check(decisions["COMMIT"] > 0, "At least one transfer committed")
        check(after == expected_balances, "Balances match committed transfers")
        check(sum(after) == sum(before), "Money is conserved across the two accounts")
        check(
            total_money() == total_before,
            "Total money across both shard databases is unchanged",
        )

    finish()


if __name__ == "__main__":
    main()
