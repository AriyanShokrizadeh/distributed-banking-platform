"""Liveness and database readiness endpoints for a banking replica."""

from fastapi import APIRouter, HTTPException, Request
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout

from services.banking.config import settings

router = APIRouter()


# Health checks


@router.get("/health/live")
def live() -> dict[str, str]:
    return {
        "status": "alive",
        "shard": settings.shard_id,
        "replica": settings.replica_id,
    }


@router.get("/health/ready")
def ready(request: Request) -> dict[str, str]:
    try:
        with request.app.state.pool.connection() as conn:
            row = conn.execute("SHOW max_prepared_transactions").fetchone()
            enabled = row is not None and int(row[0]) > 0

    except (DatabaseError, PoolTimeout) as exc:
        raise HTTPException(503, detail="Database unavailable") from exc

    if not enabled:
        raise HTTPException(503, detail="PostgreSQL 2PC is disabled")
    return {
        "status": "ready",
        "shard": settings.shard_id,
        "replica": settings.replica_id,
    }
