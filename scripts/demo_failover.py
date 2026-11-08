"""Experiment 4: stop a replica under load and continue through the healthy replica."""

import time
from collections import Counter
from threading import Event, Thread

import httpx

from scripts.common import (
    GATEWAY_URL,
    check,
    compose as run_compose,
    finish,
    step,
    title,
)


def compose(action: str) -> None:
    run_compose(action, "bank_a1")


def wait_for_failover(http: httpx.Client, timeout: float = 35) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = http.get("/v1/accounts/A0500/balance")
            response.raise_for_status()
            if response.headers.get("X-Replica-ID") == "A2":
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError("Gateway did not select replica A2")


def main() -> None:
    title(4, "Replica interruption")
    with httpx.Client(base_url=GATEWAY_URL, timeout=3) as http:
        http.get("/health/ready").raise_for_status()
        stop_load = Event()
        handled: Counter[str] = Counter()
        failures: list[str] = []

        def send_requests() -> None:
            while not stop_load.is_set():
                try:
                    response = http.get("/v1/accounts/A0500/balance")
                    response.raise_for_status()
                    handled[response.headers.get("X-Replica-ID", "unknown")] += 1
                except httpx.HTTPError as exc:
                    failures.append(str(exc))
                stop_load.wait(0.05)

        step("Start continuous balance requests")
        load = Thread(target=send_requests, daemon=True)
        stopped = False
        load.start()
        try:
            time.sleep(1)
            step("Stop bank_a1 while requests are running")
            compose("stop")
            stopped = True
            wait_for_failover(http)
            time.sleep(1)
            check(handled["A2"] > 0, "Healthy replica A2 continued serving requests")
        finally:
            stop_load.set()
            load.join(timeout=4)
            if stopped:
                step("Restore bank_a1")
                compose("start")

        print(f"  Served by replicas: {dict(handled)}")
        print(f"  Temporary request errors: {len(failures)}")
    finish()


if __name__ == "__main__":
    main()
