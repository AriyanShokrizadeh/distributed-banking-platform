"""Experiment 3: concurrent writes avoid lost updates and overdrafts."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

from scripts.common import balance, check, client, finish, post, step, title

ACCOUNT = "A0921"
OVERDRAFT_ACCOUNT = "A0926"


def main() -> None:
    title(3, "Concurrent replica operations")
    with client() as http:
        before = balance(http, ACCOUNT)
        jobs = [("deposits", 5)] * 10 + [("withdrawals", 3)] * 10

        def send(job: tuple[str, int]) -> httpx.Response:
            action, amount = job
            return post(
                http,
                f"/v1/accounts/{ACCOUNT}/{action}",
                {"amount_minor": amount},
            )

        step("20 concurrent deposits and withdrawals on the same account")

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(send, jobs))
        for response in responses:
            response.raise_for_status()

        replicas = Counter(response.headers.get("X-Replica-ID", "missing") for response in responses)
        expected = before + 10 * 5 - 10 * 3
        print(f"  {ACCOUNT}: {before} -> {balance(http, ACCOUNT)} (expected {expected})")
        print(f"  Replicas: {dict(replicas)}")
        check(balance(http, ACCOUNT) == expected, "No lost updates")
        check(
            "missing" not in replicas and len(replicas) >= 2,
            "Both replicas processed writes",
        )

        step("15 concurrent withdrawals: insufficient funds are rejected")

        current = balance(http, OVERDRAFT_ACCOUNT)
        if current != 1000:
            action = "deposits" if current < 1000 else "withdrawals"
            post(
                http,
                f"/v1/accounts/{OVERDRAFT_ACCOUNT}/{action}",
                {"amount_minor": abs(1000 - current)},
            ).raise_for_status()

        def withdraw(_: int) -> httpx.Response:
            return post(
                http,
                f"/v1/accounts/{OVERDRAFT_ACCOUNT}/withdrawals",
                {"amount_minor": 100},
            )

        with ThreadPoolExecutor(max_workers=10) as pool:
            responses = list(pool.map(withdraw, range(15)))
        codes = Counter(response.status_code for response in responses)
        print(f"  Responses: {dict(codes)}")
        print(f"  Final balance: {balance(http, OVERDRAFT_ACCOUNT)}")
        check(codes == {200: 10, 409: 5}, "Exactly 10 withdrawals succeeded")
        check(balance(http, OVERDRAFT_ACCOUNT) == 0, "Balance never became negative")

    finish()


if __name__ == "__main__":
    main()
