"""Proxy requests to healthy shard replicas or the 2PC Coordinator."""

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from shared.api import internal_headers

logger = logging.getLogger("banking.gateway")


def gateway_response(upstream: httpx.Response) -> Response:
    """Preserve the upstream status, JSON body, and replica-identifying headers."""
    headers = {
        name: upstream.headers[name] for name in ("x-replica-id", "x-shard-id") if name in upstream.headers
    }
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
    """Try the next replica only after a transport failure, never an HTTP error."""
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
        detail={
            "code": "UNCERTAIN_OUTCOME",
            "message": "Upstream unavailable. Retry using the same Idempotency-Key.",
        },
    )


def shard_proxy(
    request: Request,
    shard: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    key: UUID | None = None,
) -> Response:
    registry = request.app.state.registry
    replicas = registry.candidates(shard)
    if not replicas:
        raise HTTPException(
            503,
            detail={
                "code": "NO_HEALTHY_REPLICAS",
                "message": f"Shard {shard} is temporarily unavailable",
            },
        )

    return forward(
        request.app.state.client,
        replicas,
        request.app.state.token,
        method,
        path,
        body,
        key,
        mark_down=registry.set_health,
    )


def coordinator_proxy(
    request: Request,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    key: UUID | None = None,
) -> Response:
    return forward(
        request.app.state.client,
        [request.app.state.coordinator_url],
        request.app.state.token,
        method,
        path,
        body,
        key,
        timeout=8,
    )
