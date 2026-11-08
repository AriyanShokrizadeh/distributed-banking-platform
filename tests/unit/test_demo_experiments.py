"""Mocked checks for the public demo clients; no Docker is needed."""

import sys
from uuid import UUID

import httpx
import pytest

from scripts import common, demo_load_balancing, demo_sharding


def test_post_uses_uuid_and_preserves_supplied_key() -> None:
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request.headers["Idempotency-Key"])
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)) as http:
        common.post(http, "/v1/accounts/A0500/deposits", {"amount_minor": 5})
        key = UUID("81cd7af0-7e53-45c8-a82b-55173d5e2ca9")
        common.post(http, "/v1/accounts/A0500/deposits", {"amount_minor": 5}, key)

    assert isinstance(UUID(received[0]), UUID)
    assert received[1] == str(key)


def test_transaction_polling_returns_completed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        state = "PENDING" if calls == 1 else "COMPLETED"
        return httpx.Response(200, json={"status": state, "decision": "COMMIT"})

    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)) as http:
        result = common.wait_for_transaction(http, "a-transaction")

    assert calls == 2
    assert result["decision"] == "COMMIT"


def test_sharding_demo_checks_database_and_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        account = request.url.path.split("/")[3]
        shard = "A" if int(account[1:]) <= 1000 else "B"
        seen.append(account)
        return httpx.Response(
            200,
            json={"balance_minor": 1000},
            headers={"X-Shard-ID": shard, "X-Replica-ID": shard + "1"},
        )

    def summary(shard: dict) -> tuple[int, str, str, int]:
        return (1000, f"A{shard['start']:04d}", f"A{shard['end']:04d}", 0)

    monkeypatch.setattr(demo_sharding, "database_summary", summary)
    monkeypatch.setattr(demo_sharding, "client", lambda: http)
    http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    demo_sharding.main()

    assert seen == ["A0001", "A1000", "A1001", "A2000"]


def test_load_balancing_demo_reports_both_replicas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"balance_minor": 1000},
            headers={"X-Replica-ID": "A1" if calls % 2 else "A2"},
        )

    monkeypatch.setattr(sys, "argv", ["demo_load_balancing.py", "--requests", "6"])
    monkeypatch.setattr(demo_load_balancing, "client", lambda: http)
    http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    demo_load_balancing.main()
    assert calls == 6


def test_load_balancing_demo_detects_single_replica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["demo_load_balancing.py", "--requests", "4"])
    monkeypatch.setattr(demo_load_balancing, "client", lambda: http)
    http = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"balance_minor": 1000}, headers={"X-Replica-ID": "A1"})
        ),
    )
    with pytest.raises(RuntimeError, match="Requests reached both replicas"):
        demo_load_balancing.main()
