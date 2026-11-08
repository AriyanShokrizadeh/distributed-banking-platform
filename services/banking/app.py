"""FastAPI application for each banking-shard replica."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from services.banking.routes import health, router, settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    with ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=16,
        timeout=5,
        kwargs={"autocommit": True},
    ) as pool:
        app.state.pool = pool
        yield


app = FastAPI(
    title=f"Banking Shard {settings.shard_id} Replica {settings.replica_id}",
    lifespan=lifespan,
)
app.include_router(health)
app.include_router(router)
