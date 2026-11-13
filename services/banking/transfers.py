"""Execute transfers between accounts owned by the same shard."""

from uuid import UUID, uuid4

from psycopg_pool import ConnectionPool

from services.banking.accounts import account_not_found
from services.banking.receipts import AccountCursor, execute_once
from shared.api import Result, error
from shared.contracts import MAX_BIGINT


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
