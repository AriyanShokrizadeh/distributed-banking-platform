"""HTTP API and lifecycle for the durable 2PC coordinator."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg import Connection, Error as DatabaseError
from psycopg.rows import TupleRow, tuple_row
from psycopg_pool import ConnectionPool, PoolTimeout

from shared.api import IdempotencyKey
from shared.auth import require_internal
from shared.contracts import TransferRequest
from shared.observability import observe
from shared.settings import CoordinatorSettings
from shared.sharding import ShardMap
from services.coordinator.engine import Engine
from services.coordinator.store import (
    IdempotencyConflict,
    create_transaction,
    get_transaction,
    public_status,
)

settings = CoordinatorSettings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    token = settings.require_token()
    with ConnectionPool(
        settings.require_database_url(),
        connection_class=Connection[TupleRow],
        min_size=2,
        max_size=24,
        timeout=5,
        kwargs={"autocommit": True, "row_factory": tuple_row},
    ) as pool:
        shard_map = ShardMap.from_file(settings.shard_map_path)
        engine = Engine(
            pool,
            {shard.shard_id: list(shard.replicas) for shard in shard_map.shards},
            token,
        )
        state = app.state
        state.pool = pool
        state.shard_map = shard_map
        state.engine = engine
        engine.start()
        try:
            yield
        finally:
            engine.stop()


app = FastAPI(title="Durable Distributed Banking 2PC Coordinator", lifespan=lifespan)
router = APIRouter(prefix="/internal/2pc", dependencies=[Depends(require_internal)])


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "alive", "service": "coordinator"}


@app.get("/health/ready")
def ready(request: Request) -> dict[str, str]:
    try:
        with request.app.state.pool.connection() as conn:
            conn.execute("SELECT 1")
    except (DatabaseError, PoolTimeout) as exc:
        raise HTTPException(503, detail="Coordinator database unavailable") from exc

    return {"status": "ready", "service": "coordinator"}


@router.post("/transfers", response_model=None)
def transfer(
    payload: TransferRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any] | JSONResponse:
    try:
        state = request.app.state
        txid = create_transaction(state.pool, state.shard_map, payload, idempotency_key)
        state.engine.wake()

        transaction = get_transaction(state.pool, txid)
        if transaction is None:
            raise RuntimeError("Transaction missing after creation")

        result = public_status(transaction)
        if transaction["status"] != "COMPLETED":
            return JSONResponse(status_code=202, content=result)
        return result

    except IdempotencyConflict as exc:
        raise HTTPException(
            409,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            422,
            detail={"code": "INVALID_TRANSFER", "message": str(exc)},
        ) from exc
    except (DatabaseError, PoolTimeout) as exc:
        raise HTTPException(503, detail={"code": "COORDINATOR_DB_UNAVAILABLE"}) from exc


@router.get("/transactions/{transaction_id}")
def transaction_status(transaction_id: UUID, request: Request) -> dict[str, Any]:
    try:
        transaction = get_transaction(request.app.state.pool, transaction_id)
    except (DatabaseError, PoolTimeout) as exc:
        raise HTTPException(503, detail={"code": "COORDINATOR_DB_UNAVAILABLE"}) from exc

    if transaction is None:
        raise HTTPException(404, detail={"code": "TRANSACTION_NOT_FOUND"})
    return public_status(transaction)


app.include_router(router)

observe(app, "coordinator")
