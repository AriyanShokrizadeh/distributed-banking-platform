"""Internal HTTP endpoints and shard-level validation."""

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from psycopg import Error as DatabaseError
from psycopg_pool import ConnectionPool, PoolTimeout

from services.banking import accounts, participant, transfers
from services.banking.config import settings
from shared.api import IdempotencyKey, Result, as_response
from shared.auth import require_internal
from shared.contracts import AmountRequest, TransferRequest
from shared.sharding import ShardRouteError, account_number
from shared.two_phase import DecisionMessage, PrepareMessage

router = APIRouter(prefix="/internal", dependencies=[Depends(require_internal)])


def check_owner(account_id: str) -> None:
    try:
        number = account_number(account_id)
    except ShardRouteError as exc:
        raise HTTPException(
            422,
            detail={"code": "INVALID_ACCOUNT_ID", "message": str(exc)},
        ) from exc

    if not settings.shard_start <= number <= settings.shard_end:
        raise HTTPException(
            409,
            detail={
                "code": "SHARD_MISMATCH",
                "message": (f"Account {account_id} does not belong to shard {settings.shard_id}"),
            },
        )


def run_operation(request: Request, operation: Callable[[ConnectionPool], Result]) -> Response:
    """Run one banking operation and attach shard metadata to its response."""
    try:
        result = operation(request.app.state.pool)
    except (DatabaseError, PoolTimeout) as exc:
        raise HTTPException(
            503,
            detail={
                "code": "DATABASE_UNAVAILABLE",
                "message": "Retry using the same Idempotency-Key",
            },
        ) from exc
    return as_response(
        result,
        {"X-Replica-ID": settings.replica_id, "X-Shard-ID": settings.shard_id},
    )


def change_account_balance(
    account_id: str,
    payload: AmountRequest,
    request: Request,
    key: UUID,
    operation: str,
) -> Response:
    check_owner(account_id)
    return run_operation(
        request,
        lambda pool: accounts.change_balance(
            pool,
            account_id,
            payload.amount_minor,
            key,
            operation,
        ),
    )


# Account operations


@router.get("/accounts/{account_id}/balance")
def balance(account_id: str, request: Request) -> Response:
    check_owner(account_id)
    return run_operation(request, lambda pool: accounts.read_balance(pool, account_id))


@router.post("/accounts/{account_id}/deposits")
def deposit(
    account_id: str,
    payload: AmountRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
) -> Response:
    return change_account_balance(account_id, payload, request, idempotency_key, "DEPOSIT")


@router.post("/accounts/{account_id}/withdrawals")
def withdraw(
    account_id: str,
    payload: AmountRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
) -> Response:
    return change_account_balance(account_id, payload, request, idempotency_key, "WITHDRAW")


@router.post("/transfers/local")
def transfer_local(
    payload: TransferRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
) -> Response:
    check_owner(payload.source_account)
    check_owner(payload.destination_account)
    return run_operation(
        request,
        lambda pool: transfers.local_transfer(
            pool,
            payload.source_account,
            payload.destination_account,
            payload.amount_minor,
            idempotency_key,
        ),
    )


# Cross-shard two-phase commit


@router.post("/2pc/prepare")
def prepare_2pc(payload: PrepareMessage, request: Request) -> Response:
    check_owner(payload.account_id)
    return run_operation(
        request,
        lambda pool: participant.prepare(
            pool,
            settings.shard_id,
            payload,
        ),
    )


def handle_decision(payload: DecisionMessage, request: Request, decision: str) -> Response:
    return run_operation(
        request,
        lambda pool: participant.decide(pool, settings.shard_id, payload, decision),
    )


@router.post("/2pc/commit")
def commit_2pc(payload: DecisionMessage, request: Request) -> Response:
    return handle_decision(payload, request, "COMMIT")


@router.post("/2pc/abort")
def abort_2pc(payload: DecisionMessage, request: Request) -> Response:
    return handle_decision(payload, request, "ABORT")


@router.get("/2pc/{transaction_id}")
def status_2pc(transaction_id: UUID, request: Request) -> Response:
    return run_operation(
        request,
        lambda pool: Result(200, participant.status(pool, settings.shard_id, transaction_id)),
    )
