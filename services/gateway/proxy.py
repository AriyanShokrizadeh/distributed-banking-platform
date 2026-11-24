"""Forward requests to a shard replica or the durable 2PC Coordinator.

On a transport error, retry with the *same* idempotency key. Never interpret
an unavailable upstream as a failed banking transaction: its result is unknown.
"""

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from shared.auth import internal_headers

logger = logging.getLogger("banking.gateway")
REPLICA_HEADERS = ("x-replica-id", "x-shard-id")
UNCERTAIN_OUTCOME_MESSAGE = "Upstream unavailable. Retry using the same Idempotency-Key."


def gateway_response(upstream: httpx.Response) -> Response:
    """Preserve HTTP status, body and replica headers from the upstream."""
    headers = {name: upstream.headers[name] for name in REPLICA_HEADERS if name in upstream.headers}
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type="application/json",
        headers=headers,
    )


def forward(
    client: httpx.Client,
    urls: list[str],
    token: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    key: UUID | None = None,
    mark_down: Callable[[str, bool], None] | None = None,
    timeout: float = 10,
) -> Response:
    """Use the next replica only for transport failures, not HTTP errors.

    In particular, an HTTP 409 is returned immediately and an uncertain POST
    is never retried with a *different* Idempotency-Key.
    """
    headers = internal_headers(token, key)
    request_timeout = httpx.Timeout(timeout, connect=1.5)

    for url in urls:
        try:
            upstream = client.request(
                method,
                url + path,
                json=body,
                headers=headers,
                timeout=request_timeout,
            )
        except httpx.RequestError:
            if mark_down is not None:
                mark_down(url, False)
            continue

        logger.info(
            "upstream=%s method=%s path=%s status=%s",
            url,
            method,
            path,
            upstream.status_code,
        )
        return gateway_response(upstream)

    raise HTTPException(
        503,
        detail={"code": "UNCERTAIN_OUTCOME", "message": UNCERTAIN_OUTCOME_MESSAGE},
    )


def shard_proxy(
    request: Request,
    shard: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    key: UUID | None = None,
) -> Response:
    """Forward only to replicas declared healthy for the requested shard."""
    state = request.app.state
    candidates = state.registry.candidates(shard)
    if not candidates:
        raise HTTPException(
            503,
            detail={
                "code": "NO_HEALTHY_REPLICAS",
                "message": f"Shard {shard} is temporarily unavailable",
            },
        )

    return forward(
        state.client,
        candidates,
        state.token,
        method,
        path,
        body,
        key,
        mark_down=state.registry.set_health,
    )


def coordinator_proxy(
    request: Request,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    key: UUID | None = None,
) -> Response:
    """Reach the Coordinator through its stable service endpoint."""
    state = request.app.state
    return forward(
        state.client,
        [state.coordinator_url],
        state.token,
        method,
        path,
        body,
        key,
        timeout=8,
    )
