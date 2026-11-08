"""Experiment 1: account placement and shard-aware Gateway routing."""

import json

from scripts.common import ROOT, check, client, finish, sql, step, title


def database_summary(shard: dict) -> tuple[int, str, str, int]:
    start, end = f"A{shard['start']:04d}", f"A{shard['end']:04d}"
    result = sql(
        f"db_{shard['id'].lower()}",
        "SELECT COUNT(*), MIN(account_id), MAX(account_id), "
        f"COUNT(*) FILTER (WHERE account_id < '{start}' OR account_id > '{end}') "
        "FROM accounts",
    )
    count, first, last, misplaced = result.split("|")
    return int(count), first, last, int(misplaced)


def main() -> None:
    title(1, "Shard distribution")
    mapping = json.loads((ROOT / "config/shard_map.json").read_text(encoding="utf-8"))

    with client() as http:
        for shard in mapping["shards"]:
            name = shard["id"]
            step(f"Shard {name}: inspect database and Gateway")
            count, first, last, misplaced = database_summary(shard)
            expected = shard["end"] - shard["start"] + 1
            print(f"  Database: {count} accounts, {first} .. {last}")
            check(
                count == expected and misplaced == 0,
                f"Shard {name} stores its own accounts",
            )
            check(
                (first, last) == (f"A{shard['start']:04d}", f"A{shard['end']:04d}"),
                f"Shard {name} has the expected range",
            )

            for account in (first, last):
                response = http.get(f"/v1/accounts/{account}/balance")
                response.raise_for_status()
                replica = response.headers.get("X-Replica-ID")
                print(f"  {account} -> Shard {response.headers.get('X-Shard-ID')}, Replica {replica}")
                check(
                    response.headers.get("X-Shard-ID") == name and bool(replica),
                    f"Gateway routed {account} correctly",
                )

    finish()


if __name__ == "__main__":
    main()
