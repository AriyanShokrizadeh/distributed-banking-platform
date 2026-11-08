"""Durable coordinator transactions and participant acknowledgments."""

from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection, sql
from psycopg.rows import TupleRow, dict_row
from psycopg_pool import ConnectionPool

from services.coordinator.state_machine import assert_decision_not_reversed
from shared.contracts import TransferRequest
from shared.sharding import ShardMap
from shared.two_phase import prepared_gid, transfer_hash

DatabasePool = ConnectionPool[Connection[TupleRow]]


class IdempotencyConflict(ValueError):
    pass


def create_transaction(
    pool: DatabasePool,
    shard_map: ShardMap,
    request: TransferRequest,
    key: UUID,
) -> UUID:
    if request.source_account == request.destination_account:
        raise ValueError("Source and destination must differ")

    source = shard_map.owner(request.source_account).shard_id
    destination = shard_map.owner(request.destination_account).shard_id
    if source == destination:
        raise ValueError("Coordinator handles only cross-shard transfers")

    fingerprint = transfer_hash(
        request.source_account,
        request.destination_account,
        request.amount_minor,
    )

    with (
        pool.connection() as conn,
        conn.transaction(),
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        row = cursor.execute(
            """
            INSERT INTO distributed_transactions (
                transaction_id, client_request_id, request_hash,
                source_account, destination_account, source_shard,
                destination_shard, amount_minor, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'INITIATED')
            ON CONFLICT (client_request_id) DO NOTHING
            RETURNING transaction_id
            """,
            (
                uuid4(),
                key,
                fingerprint,
                request.source_account,
                request.destination_account,
                source,
                destination,
                request.amount_minor,
            ),
        ).fetchone()

        if row is not None:
            txid = row["transaction_id"]
            cursor.executemany(
                """
                INSERT INTO transaction_participants (transaction_id, shard_id, prepared_gid)
                VALUES (%s, %s, %s)
                """,
                [
                    (txid, shard, prepared_gid(shard, txid, fingerprint))
                    for shard in sorted((source, destination))
                ],
            )
            return txid

        stored = cursor.execute(
            """
            SELECT transaction_id, request_hash
            FROM distributed_transactions
            WHERE client_request_id = %s
            """,
            (key,),
        ).fetchone()

        if stored is None:
            raise RuntimeError("Transaction disappeared")
        if stored["request_hash"] != fingerprint:
            raise IdempotencyConflict("Idempotency-Key reused with different transfer details")
        return stored["transaction_id"]


def get_transaction(pool: DatabasePool, txid: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        tx = cursor.execute(
            "SELECT * FROM distributed_transactions WHERE transaction_id = %s",
            (txid,),
        ).fetchone()

        if tx is not None:
            tx["participants"] = cursor.execute(
                """
                SELECT shard_id, prepare_ack_at, decision_ack_at
                FROM transaction_participants
                WHERE transaction_id = %s
                ORDER BY shard_id
                """,
                (txid,),
            ).fetchall()
        return tx


def public_status(tx: dict[str, Any]) -> dict[str, Any]:
    return {
        "transaction_id": str(tx["transaction_id"]),
        "status": "COMPLETED" if tx["status"] == "COMPLETED" else "PENDING",
        "internal_status": tx["status"],
        "decision": tx["decision"],
        "source_account": tx["source_account"],
        "destination_account": tx["destination_account"],
        "amount_minor": tx["amount_minor"],
        "participants": [
            {
                "shard": participant["shard_id"],
                "prepared": bool(participant["prepare_ack_at"]),
                "decision_acknowledged": bool(participant["decision_ack_at"]),
            }
            for participant in tx["participants"]
        ],
    }


def pending_ids(pool: DatabasePool) -> list[UUID]:
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """
            SELECT transaction_id FROM distributed_transactions
            WHERE status <> 'COMPLETED'
            ORDER BY created_at
            LIMIT 256
            """
        ).fetchall()
        return [row["transaction_id"] for row in rows]


def set_status(pool: DatabasePool, txid: UUID, state: str) -> None:
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            """
            UPDATE distributed_transactions
            SET status = %s, updated_at = NOW()
            WHERE transaction_id = %s AND decision IS NULL
            """,
            (state, txid),
        )


def record_prepare_ack(pool: DatabasePool, txid: UUID, shard: str) -> None:
    record_acknowledgment(pool, txid, shard, "prepare_ack_at")


def record_decision(pool: DatabasePool, txid: UUID, decision: str) -> None:
    state = "COMMIT_DECIDED" if decision == "COMMIT" else "ABORT_DECIDED"

    with pool.connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            SELECT decision FROM distributed_transactions
            WHERE transaction_id = %s FOR UPDATE
            """,
            (txid,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Transaction missing")

        existing_decision = row["decision"]
        assert_decision_not_reversed(existing_decision, decision)
        if existing_decision is not None:
            return

        cursor.execute(
            """
            UPDATE distributed_transactions
            SET status = %s, decision = %s,
                decided_at = NOW(), updated_at = NOW()
            WHERE transaction_id = %s
            """,
            (state, decision, txid),
        )


def record_acknowledgment(pool: DatabasePool, txid: UUID, shard: str, column: str) -> None:
    """Persist a participant acknowledgment, retaining its first timestamp."""
    if column not in ("prepare_ack_at", "decision_ack_at"):
        raise ValueError("Unknown acknowledgment type")

    statement = sql.SQL(
        "UPDATE transaction_participants "
        "SET {column} = COALESCE({column}, NOW()) "
        "WHERE transaction_id = %s AND shard_id = %s"
    ).format(column=sql.Identifier(column))
    with pool.connection() as conn, conn.transaction():
        conn.execute(statement, (txid, shard))


def record_decision_ack(pool: DatabasePool, txid: UUID, shard: str) -> None:
    record_acknowledgment(pool, txid, shard, "decision_ack_at")


def complete_if_all_acknowledged(pool: DatabasePool, txid: UUID) -> None:
    with pool.connection() as conn, conn.transaction():
        conn.execute(
            """
            UPDATE distributed_transactions
            SET status = 'COMPLETED', updated_at = NOW()
            WHERE transaction_id = %s AND decision IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM transaction_participants
                  WHERE transaction_id = %s AND decision_ack_at IS NULL
              )
            """,
            (txid, txid),
        )


def first_fault(pool: DatabasePool, label: str) -> bool:
    """Persist the one-shot marker before a simulated crash."""
    with pool.connection() as conn, conn.transaction():
        row = conn.execute(
            """
            INSERT INTO fault_injections (name) VALUES (%s)
            ON CONFLICT DO NOTHING RETURNING name
            """,
            (label,),
        ).fetchone()
        return row is not None
