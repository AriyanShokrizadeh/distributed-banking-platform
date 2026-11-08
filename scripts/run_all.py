"""Run the seven assignment experiments in order, or select experiments by number."""

import argparse
import subprocess
import sys

from scripts.common import ROOT

EXPERIMENTS = {
    "1": "demo_sharding",
    "2": "demo_load_balancing",
    "3": "demo_concurrency",
    "4": "demo_failover",
    "5": "demo_transfers",
    "6": "demo_2pc_crash",
    "7": "demo_cross_shard",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "experiments",
        nargs="*",
        choices=EXPERIMENTS,
        help="Experiment numbers (default: all)",
    )
    selection = parser.parse_args().experiments or list(EXPERIMENTS)

    for number in selection:
        module = EXPERIMENTS[number]
        print(f"\nRunning experiment {number}: {module}", flush=True)
        subprocess.run([sys.executable, "-m", f"scripts.{module}"], cwd=ROOT, check=True)

    print(f"\nPASS: {len(selection)} experiment(s) completed", flush=True)


if __name__ == "__main__":
    main()
