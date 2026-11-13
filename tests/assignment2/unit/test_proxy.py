"""Gateway retries only on transport errors, preserving request identity."""

from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from services.gateway.proxy import forward
from tests.common import mock_client


def test_transport_error_retries_next_replica_with_same_idempotency_key():
    key = uuid4()
    requests = []
    failed_replicas = []

    def handle(request):
        requests.append(request)
        if request.url.host == "failed":
            raise httpx.ConnectError("connection lost")
        return httpx.Response(200, json={"ok": True}, headers={"X-Replica-ID": "A2"})

    with mock_client(handle) as client:
        response = forward(
            client,
            ["http://failed", "http://healthy"],
            "token",
            "POST",
            "/internal/accounts/A0500/deposits",
            {"amount_minor": 2},
            key,
            mark_down=lambda url, healthy: failed_replicas.append((url, healthy)),
        )

    assert response.status_code == 200
    assert response.headers["x-replica-id"] == "A2"
    assert failed_replicas == [("http://failed", False)]
    assert [request.url.host for request in requests] == ["failed", "healthy"]
    assert all(request.headers["idempotency-key"] == str(key) for request in requests)
    assert all(request.headers["x-internal-token"] == "token" for request in requests)


def test_http_conflict_is_returned_without_retry():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(409, json={"error": "reused key"})

    with mock_client(handle) as client:
        response = forward(client, ["http://one", "http://two"], "token", "POST", "/test")

    assert response.status_code == 409
    assert len(requests) == 1


def test_all_unreachable_replicas_return_uncertain_outcome():
    def unreachable(_request):
        raise httpx.ConnectError("unreachable")

    with mock_client(unreachable) as client:
        with pytest.raises(HTTPException) as error:
            forward(client, ["http://one", "http://two"], "token", "POST", "/test")

    assert error.value.status_code == 503
