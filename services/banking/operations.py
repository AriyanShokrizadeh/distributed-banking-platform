"""Atomic account operations and local transfers."""

from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.banking.receipts import AccountCursor, execute_once
from shared.api import Result, error
from shared.contracts import MAX_BIGINT, balance_limits


def account_not_found(account_id: str) -> Result:
    return error("ACCOUNT_NOT_FOUND", f"Account {account_id} does not exist", 404)


def update_balance(cursor: AccountCursor, account_id: str, delta: int) -> int | None:
    """Update a balance only when its result fits the allowed range."""
    lower, upper = balance_limits(delta)
    row = cursor.execute(
        """
        UPDATE accounts SET balance_minor = balance_minor + %s
        WHERE account_id = %s AND balance_minor BETWEEN %s AND %s
        RETURNING balance_minor
        """,
        (delta, account_id, lower, upper),
    ).fetchone()
    return row["balance_minor"] if row else None


def read_balance(pool: ConnectionPool, account_id: str) -> Result:
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "SELECT balance_minor FROM accounts WHERE account_id = %s",
            (account_id,),
        ).fetchone()

    if row is None:
        return account_not_found(account_id)
    return Result(
        200,
        {"account_id": account_id, "balance_minor": row["balance_minor"]},
    )


def change_balance(
    pool: ConnectionPool,
    account_id: str,
    amount_minor: int,
    key: UUID,
    kind: str,
) -> Result:
    delta = amount_minor if kind == "DEPOSIT" else -amount_minor

    def mutate(cursor: AccountCursor) -> Result:
        balance = update_balance(cursor, account_id, delta)
        if balance is not None:
            return Result(
                200,
                {"account_id": account_id, "balance_minor": balance, "operation": kind},
            )

        exists = cursor.execute(
            "SELECT 1 FROM accounts WHERE account_id = %s",
            (account_id,),
        ).fetchone()
        if exists is None:
            return account_not_found(account_id)
        if delta > 0:
            return error("BALANCE_OVERFLOW", "Balance would exceed BIGINT range", 409)
        return error("INSUFFICIENT_FUNDS", "Insufficient available balance", 409)

    return execute_once(
        pool,
        key,
        kind,
        {"account_id": account_id, "amount_minor": amount_minor},
        mutate,
    )


def apply_local_transfer(cursor: AccountCursor, source: str, destination: str, amount_minor: int) -> UUID:
    """Apply both balance changes and write matching ledger entries atomically."""
    transaction_id = uuid4()
    changes = ((source, -amount_minor), (destination, amount_minor))

    for account_id, delta in changes:
        cursor.execute(
            "UPDATE accounts SET balance_minor = balance_minor + %s WHERE account_id = %s",
            (delta, account_id),
        )

    cursor.executemany(
        """
        INSERT INTO transfer_entries(transaction_id, account_id, delta_minor)
        VALUES (%s, %s, %s)
        """,
        [(transaction_id, account_id, delta) for account_id, delta in changes],
    )
    return transaction_id


def local_transfer(
    pool: ConnectionPool,
    source: str,
    destination: str,
    amount_minor: int,
    key: UUID,
) -> Result:
    def mutate(cursor: AccountCursor) -> Result:
        if source == destination:
            return error("SAME_ACCOUNT", "Source and destination must differ", 422)

        balances: dict[str, int] = {}

        for account_id in sorted((source, destination)):
            row = cursor.execute(
                "SELECT balance_minor FROM accounts WHERE account_id = %s FOR UPDATE",
                (account_id,),
            ).fetchone()
            if row is None:
                return account_not_found(account_id)
            balances[account_id] = row["balance_minor"]

        if balances[source] < amount_minor:
            return error("INSUFFICIENT_FUNDS", "Insufficient available balance", 409)
        if balances[destination] > MAX_BIGINT - amount_minor:
            return error("BALANCE_OVERFLOW", "Destination balance would overflow", 409)

        transaction_id = apply_local_transfer(cursor, source, destination, amount_minor)
        return Result(
            200,
            {
                "transaction_id": str(transaction_id),
                "status": "COMPLETED",
                "decision": "COMMIT",
                "source_account": source,
                "destination_account": destination,
                "amount_minor": amount_minor,
            },
        )

    return execute_once(
        pool,
        key,
        "LOCAL_TRANSFER",
        {
            "source_account": source,
            "destination_account": destination,
            "amount_minor": amount_minor,
        },
        mutate,
    )
