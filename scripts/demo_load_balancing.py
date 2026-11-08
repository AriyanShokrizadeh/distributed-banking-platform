"""Experiment 2: Round Robin distributes requests across healthy replicas."""

import argparse
from collections import Counter

from scripts.common import check, client, finish, step, title


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default="A0500")
    parser.add_argument("--requests", type=int, default=20)
    args = parser.parse_args()

    if args.requests < 2:
        parser.error("--requests must be at least 2")

    title(2, "Replica load balancing")
    step(f"Send {args.requests} balance requests for {args.account}")
    counts: Counter[str] = Counter()

    with client() as http:
        for _ in range(args.requests):
            response = http.get(f"/v1/accounts/{args.account}/balance")
            response.raise_for_status()
            replica = response.headers.get("X-Replica-ID")
            if not replica:
                raise RuntimeError("Missing X-Replica-ID header")
            counts[replica] += 1

    step("Requests handled by each replica")
    for replica, count in sorted(counts.items()):
        print(f"  {replica}: {count:>3}  {'#' * count}")
    check(len(counts) >= 2, "Requests reached both replicas")
    check(
        max(counts.values()) - min(counts.values()) <= 1,
        "Round Robin spread is balanced",
    )
    finish()


if __name__ == "__main__":
    main()
