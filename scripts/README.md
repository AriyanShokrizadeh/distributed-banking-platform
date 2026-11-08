# Banking platform — demo scripts

These scripts demonstrate the **seven required experiments** from Assignment 2. They are based on this project's API and database schema. The attached `distributed-banking-a2/demo` folder was used for inspiration (step-by-step output and one script per experiment), **not copied**, because that repository has different routes, database names and money formats.

## Setup

Run commands from the **project root**:

```bash
cp .env.example .env
# Set BANK_DB_PASSWORD, COORD_DB_PASSWORD and INTERNAL_API_TOKEN in .env
docker compose up -d --build
python -m pip install -r requirements-dev.txt
```

## Run

Run all seven experiments in order:

```bash
python -m scripts.run_all
```

Run only selected experiments:

```bash
python -m scripts.run_all 1 2 3
```

Or execute them individually:

| # | What it proves | Command |
|---|---|---|
| 1 | Accounts are stored in the correct DB and Gateway routes to the owning shard | `python -m scripts.demo_sharding` |
| 2 | Round Robin sends requests through both replicas | `python -m scripts.demo_load_balancing` |
| 3 | Concurrent writes are correct; overdrafts are rejected | `python -m scripts.demo_concurrency` |
| 4 | Traffic continues through A2 when A1 is stopped | `python -m scripts.demo_failover` |
| 5 | Local atomic transfer; distributed COMMIT and ABORT; idempotent retry | `python -m scripts.demo_transfers` |
| 6 | Coordinator crashes after a durable decision, then recovers | `python -m scripts.demo_2pc_crash --point commit` |
| 7 | Concurrent cross-shard transfers conserve money | `python -m scripts.demo_cross_shard` |

For the additional crash point after both participants prepare:

```bash
python -m scripts.demo_2pc_crash --point prepared
```

For more read requests in experiment 2:

```bash
python -m scripts.demo_load_balancing --account A1500 --requests 50
```

## Notes

- The scripts generate **Idempotency-Key** values automatically. Repeated requests for the same operation use the same UUID.
- Set `GATEWAY_URL` to change the default address `http://127.0.0.1:8000`.
- Experiments 3, 5, 6 and 7 **modify test account balances**; only use them with test data. Experiment 3 resets the dedicated overdraft-test account (`A0926`) to 1000 minor units via the Gateway.
- Experiment 4 temporarily stops and restarts `bank_a1`. Experiment 6 deliberately crashes and recreates the Coordinator. It waits until the Coordinator is healthy before sending the test transfer and checks that uncertain HTTP responses correspond to a durable transaction. Both demos attempt to restore the affected service after an error.
- The scripts never run `docker compose down -v` or delete database volumes. Run one experiment at a time; concurrent outside traffic can invalidate balance checks.
- All money values are **integer `amount_minor` units**. The example repository uses decimal currency amounts, so its monetary conversion is not reused here.
- `scripts/common.py` contains the shared HTTP, Docker, SQL and display helpers. Each demo contains only its own scenario and checks.
- The bonus online migration and autonomous self-healing demonstrations are **not included**, because those mechanisms are not part of this project's implemented core.

## Tests

```bash
python -m pytest tests/unit -q
```

The balance helper returns an explicit `tuple[int, int]`, and the expected-balance lookup in the concurrent transfer demo uses `dict[str, int]`. Both annotations reflect the actual usage and prevent false Pylance key/tuple warnings without `type: ignore`.

These checks do not replace running the demonstrations against a live Docker Compose environment. The crash and replica interruption experiments in particular should be verified on your machine.
