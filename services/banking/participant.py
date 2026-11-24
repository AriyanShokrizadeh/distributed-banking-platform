"""PostgreSQL 2PC participant: durable votes and idempotent decisions.

A YES vote leaves a prepared PostgreSQL transaction on disk. Its balance
mutation and outcome row become visible only after COMMIT PREPARED.
"""

from contextlib import suppress
from uuid import UUID

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.banking.accounts import update_balance
from services.banking.participant_state import transaction_mutex, transaction_state
from shared.api import Result
from shared.two_phase import (
    DECISION_OUTCOME,
    DecisionMessage,
    PrepareMessage,
    prepared_gid,
)


def vote_result(status: int, vote: str, **details: str) -> Result:
    """Build a participant response with a consistent protocol shape."""
    return Result(status, {"vote": vote, **details})


def record_outcome(conn: Connection, message: PrepareMessage, outcome: str) -> None:
    """Write the outcome in the same transaction as its balance mutation."""
    conn.execute(
        """
        INSERT INTO participant_outcomes(transaction_id, request_hash, outcome)
        VALUES (%s, %s, %s)
        """,
        (message.transaction_id, message.request_hash, outcome),
    )


def refusal_reason(conn: Connection, account_id: str, delta: int) -> str:
    """Distinguish a missing account from a debit/credit constraint failure."""
    exists = conn.execute("SELECT 1 FROM accounts WHERE account_id = %s", (account_id,)).fetchone()
    if exists is None:
        return "ACCOUNT_NOT_FOUND"
    return "INSUFFICIENT_FUNDS" if delta < 0 else "BALANCE_OVERFLOW"


def prepare_new(conn: Connection, message: PrepareMessage, gid: str) -> Result:
    """Attempt a new vote; persist a NO or leave a durable prepared YES.

    Explicit SQL BEGIN/COMMIT is required because PREPARE TRANSACTION must
    terminate the transaction without psycopg managing a nested transaction.
    """
    delta = -message.amount_minor if message.operation == "DEBIT" else message.amount_minor

    conn.execute("BEGIN")
    try:
        conn.execute("SET LOCAL lock_timeout = '12s'")
        conn.execute("SET LOCAL statement_timeout = '20s'")
        with conn.cursor(row_factory=dict_row) as cursor:
            balance = update_balance(cursor, message.account_id, delta)

        if balance is None:
            reason = refusal_reason(conn, message.account_id, delta)
            record_outcome(conn, message, "ABORTED")
            conn.execute("COMMIT")
            return vote_result(200, "NO", reason=reason)

        conn.execute(
            """
            INSERT INTO transfer_entries(transaction_id, account_id, delta_minor)
            VALUES (%s, %s, %s)
            """,
            (message.transaction_id, message.account_id, delta),
        )
        record_outcome(conn, message, "COMMITTED")
        conn.execute(sql.SQL("PREPARE TRANSACTION {}").format(sql.Literal(gid)))
        return vote_result(200, "YES", state="PREPARED")
    except BaseException:
        with suppress(Exception):
            conn.execute("ROLLBACK")
        raise


def prepare(pool: ConnectionPool, shard: str, message: PrepareMessage) -> Result:
    """Vote once per transaction, including duplicate messages after restarts."""
    txid = message.transaction_id
    gid = prepared_gid(shard, txid, message.request_hash)

    with pool.connection() as conn, transaction_mutex(conn, shard, txid):
        state, stored = transaction_state(conn, shard, txid)

        if state in ("COMMITTED", "ABORTED"):
            if stored != message.request_hash:
                return vote_result(409, "CONFLICT", state=state)
            vote = "YES" if state == "COMMITTED" else "NO"
            return vote_result(200, vote, state=state)

        if state == "PREPARED":
            if stored == gid:
                return vote_result(200, "YES", state=state)
            return vote_result(409, "CONFLICT")

        if state != "UNKNOWN":
            return vote_result(409, "CONFLICT")
        return prepare_new(conn, message, gid)


def _finish_prepared(conn: Connection, gid: str, decision: str) -> None:
    """Apply the Coordinator's durable decision to one prepared transaction."""
    command = "COMMIT PREPARED" if decision == "COMMIT" else "ROLLBACK PREPARED"
    conn.execute(sql.SQL(command + " {}").format(sql.Literal(gid)))


def _remember_abort(conn: Connection, message: DecisionMessage) -> None:
    """Make an ABORT retryable even if the participant was never prepared."""
    conn.execute(
        """
        INSERT INTO participant_outcomes(transaction_id, request_hash, outcome)
        VALUES (%s, %s, 'ABORTED')
        ON CONFLICT(transaction_id) DO NOTHING
        """,
        (message.transaction_id, message.request_hash),
    )


def decide(pool: ConnectionPool, shard: str, message: DecisionMessage, decision: str) -> Result:
    """Apply COMMIT/ABORT safely, including duplicate calls after a crash."""
    if decision not in DECISION_OUTCOME:
        raise ValueError("Invalid 2PC decision")

    txid = message.transaction_id
    gid = prepared_gid(shard, txid, message.request_hash)
    expected = DECISION_OUTCOME[decision]

    with pool.connection() as conn, transaction_mutex(conn, shard, txid):
        state, stored = transaction_state(conn, shard, txid)

        if state in ("COMMITTED", "ABORTED"):
            matches = stored == message.request_hash and state == expected
            return vote_result(200 if matches else 409, "ACK" if matches else "CONFLICT", state=state)

        if state not in ("UNKNOWN", "PREPARED"):
            return vote_result(409, "CONFLICT", state=state)
        if state == "UNKNOWN" and decision == "COMMIT":
            return vote_result(409, "UNKNOWN", state=state)

        if state == "PREPARED":
            if stored != gid:
                return vote_result(409, "CONFLICT", state=state)
            _finish_prepared(conn, gid, decision)

        if decision == "ABORT":
            _remember_abort(conn, message)

        return vote_result(200, "ACK", state=expected)


def status(pool: ConnectionPool, shard: str, txid: UUID) -> dict[str, str]:
    """Read a participant's durable state under the transaction lock."""
    with pool.connection() as conn, transaction_mutex(conn, shard, txid):
        state, _ = transaction_state(conn, shard, txid)
    return {"transaction_id": str(txid), "state": state, "shard": shard}
