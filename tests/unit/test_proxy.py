"""No live services needed: mock the upstream HTTP transport."""

from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from services.gateway.proxy import forward


def test_transport_failover_preserves_idempotency_key() -> None:
    key = uuid4()
    seen: list[httpx.Request] = []
    down: list[tuple[str, bool]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "failed":
            raise httpx.ConnectError("connection lost")
        return httpx.Response(200, json={"ok": True}, headers={"X-Replica-ID": "A2"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = forward(
            client,
            ["http://failed", "http://healthy"],
            "token",
            "POST",
            "/internal/accounts/A0500/deposits",
            {"amount_minor": 2},
            key,
            mark_down=lambda url, healthy: down.append((url, healthy)),
        )
    assert response.status_code == 200
    assert response.headers["x-replica-id"] == "A2"
    assert down == [("http://failed", False)]
    assert len(seen) == 2
    assert {r.headers["idempotency-key"] for r in seen} == {str(key)}
    assert all(r.headers["x-internal-token"] == "token" for r in seen)


def test_application_conflict_is_not_retried() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(409, json={"error": "reused key"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = forward(client, ["http://one", "http://two"], "token", "POST", "/test")
    assert response.status_code == 409
    assert len(seen) == 1


def test_all_replicas_down_returns_uncertain_outcome() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(HTTPException) as error:
            forward(client, ["http://one", "http://two"], "token", "POST", "/test")
    assert error.value.status_code == 503
