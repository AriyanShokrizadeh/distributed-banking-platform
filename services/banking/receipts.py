"""Store a request receipt and its account mutation in one transaction."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import Cursor
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from shared.api import Result, error
from shared.contracts import request_fingerprint

AccountCursor = Cursor[dict[str, Any]]


def replay_receipt(cursor: AccountCursor, key: UUID, fingerprint: str, operation: str) -> Result:
    """Return a stored response or reject reuse of a key for another request."""
    receipt = cursor.execute(
        """
        SELECT request_hash, operation_type, status,
               response_http_status, response_payload
        FROM request_receipts
        WHERE request_id = %s FOR UPDATE
        """,
        (key,),
    ).fetchone()
    if receipt is None:
        raise RuntimeError("Receipt disappeared after uniqueness conflict")
    if receipt["request_hash"] != fingerprint or receipt["operation_type"] != operation:
        return error(
            "IDEMPOTENCY_KEY_REUSED",
            "The Idempotency-Key was used with different request details",
            409,
        )
    if receipt["status"] != "COMPLETED":
        raise RuntimeError("Found a committed nonterminal receipt")
    return Result(receipt["response_http_status"], receipt["response_payload"])


def execute_once(
    pool: ConnectionPool,
    key: UUID,
    operation: str,
    payload: dict[str, Any],
    mutation: Callable[[AccountCursor], Result],
) -> Result:
    """Replay completed requests without running the mutation again."""
    fingerprint = request_fingerprint(operation, payload)

    with (
        pool.connection() as conn,
        conn.transaction(),
        conn.cursor(row_factory=dict_row) as cursor,
    ):
        inserted = cursor.execute(
            """
            INSERT INTO request_receipts(
                request_id, request_hash, operation_type, status
            )
            VALUES (%s, %s, %s, 'PROCESSING')
            ON CONFLICT(request_id) DO NOTHING RETURNING request_id
            """,
            (key, fingerprint, operation),
        ).fetchone()

        if inserted is None:
            return replay_receipt(cursor, key, fingerprint, operation)

        result = mutation(cursor)
        cursor.execute(
            """
            UPDATE request_receipts
            SET status = 'COMPLETED', response_http_status = %s, response_payload = %s
            WHERE request_id = %s
            """,
            (result.status_code, Jsonb(result.body), key),
        )
        return result
