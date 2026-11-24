"""Prometheus metrics for HTTP, 2PC decisions and recovery failures."""

import time

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)
HTTP_REQUESTS = Counter(
    "banking_http_requests_total",
    "HTTP requests by service, route template and result",
    ["service", "method", "route", "status"],
    registry=REGISTRY,
)
HTTP_SECONDS = Histogram(
    "banking_http_request_duration_seconds",
    "End-to-end HTTP response duration in seconds",
    ["service", "method", "route"],
    registry=REGISTRY,
)
DECISIONS = Counter(
    "banking_2pc_decisions_total",
    "Newly persisted COMMIT or ABORT decisions",
    ["decision"],
    registry=REGISTRY,
)
RECOVERY_FAILURES = Counter(
    "banking_2pc_recovery_failures_total",
    "Failed background 2PC resolution attempts",
    registry=REGISTRY,
)


def observe(app: FastAPI, service: str) -> None:
    """Install one metrics endpoint and HTTP middleware on a FastAPI app."""

    @app.middleware("http")
    async def collect_requests(request: Request, call_next):
        start = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            template = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(service, request.method, template, str(status)).inc()
            HTTP_SECONDS.labels(service, request.method, template).observe(time.monotonic() - start)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
