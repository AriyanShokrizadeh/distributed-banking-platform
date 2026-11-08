"""Public banking API: route local requests and cross-shard transfers."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from services.gateway.proxy import coordinator_proxy, shard_proxy
from services.gateway.routing import HealthMonitor, ReplicaRegistry
from shared.api import IdempotencyKey
from shared.contracts import AmountRequest, TransferRequest
from shared.settings import GatewaySettings
from shared.sharding import ShardMap, ShardRouteError

settings = GatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    shard_map = ShardMap.from_file(settings.shard_map_path)
    registry = ReplicaRegistry(shard_map)
    app.state.shard_map = shard_map
    app.state.registry = registry
    app.state.token = settings.require_token()
    app.state.coordinator_url = settings.coordinator_url

    with httpx.Client(timeout=httpx.Timeout(10, connect=1.5)) as client:
        app.state.client = client
        monitor = HealthMonitor(registry, client)
        monitor.start()
        try:
            yield
        finally:
            monitor.stop()


app = FastAPI(title="Shard-aware Banking Gateway", lifespan=lifespan)


def owner_shard(request: Request, account_id: str) -> str:
    try:
        return request.app.state.shard_map.owner(account_id).shard_id
    except ShardRouteError as exc:
        raise HTTPException(422, detail={"code": "INVALID_ACCOUNT_ID", "message": str(exc)}) from exc


def account_change(
    account_id: str,
    payload: AmountRequest,
    request: Request,
    key: UUID,
    action: str,
) -> Response:
    """Send a deposit or withdrawal to the account's owning shard."""
    return shard_proxy(
        request,
        owner_shard(request, account_id),
        "POST",
        f"/internal/accounts/{account_id}/{action}",
        payload.model_dump(),
        key,
    )


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def ready(request: Request) -> dict:
    health = request.app.state.registry.snapshot()
    if any(not any(replicas.values()) for replicas in health.values()):
        raise HTTPException(503, detail="At least one shard has no healthy app replicas")

    try:
        response = request.app.state.client.get(
            request.app.state.coordinator_url + "/health/ready", timeout=1
        )
    except httpx.RequestError as exc:
        raise HTTPException(503, detail="Coordinator unavailable") from exc
    if response.status_code != 200:
        raise HTTPException(503, detail="Coordinator unavailable")

    return {"status": "ready", "shards": health, "coordinator": "ready"}


@app.get("/v1/internal/replicas")
def replica_health(request: Request) -> dict:
    return {
        "epoch": request.app.state.shard_map.epoch,
        "health": request.app.state.registry.snapshot(),
    }


@app.get("/v1/accounts/{account_id}/balance")
def balance(account_id: str, request: Request) -> Response:
    return shard_proxy(
        request,
        owner_shard(request, account_id),
        "GET",
        f"/internal/accounts/{account_id}/balance",
    )


@app.post("/v1/accounts/{account_id}/deposits")
def deposit(
    account_id: str,
    payload: AmountRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
) -> Response:
    return account_change(account_id, payload, request, idempotency_key, "deposits")


@app.post("/v1/accounts/{account_id}/withdrawals")
def withdraw(
    account_id: str,
    payload: AmountRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
) -> Response:
    return account_change(account_id, payload, request, idempotency_key, "withdrawals")


@app.post("/v1/transfers")
def transfer(payload: TransferRequest, request: Request, idempotency_key: IdempotencyKey) -> Response:
    source = owner_shard(request, payload.source_account)
    destination = owner_shard(request, payload.destination_account)
    body = payload.model_dump()

    if source == destination:
        return shard_proxy(request, source, "POST", "/internal/transfers/local", body, idempotency_key)

    return coordinator_proxy(request, "POST", "/internal/2pc/transfers", body, idempotency_key)


@app.get("/v1/transactions/{transaction_id}")
def transaction_status(transaction_id: UUID, request: Request) -> Response:
    return coordinator_proxy(request, "GET", f"/internal/2pc/transactions/{transaction_id}")
