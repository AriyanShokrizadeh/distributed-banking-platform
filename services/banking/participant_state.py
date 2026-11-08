"""Find durable participant state and serialize requests across replicas."""

from collections.abc import Generator
from contextlib import contextmanager
from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

from shared.two_phase import advisory_key, gid_prefix


@contextmanager
def transaction_mutex(
    conn: Connection,
    shard: str,
    txid: UUID,
) -> Generator[None, None, None]:
    """Hold a PostgreSQL session lock for the entire 2PC message."""
    key = advisory_key(f"participant-{shard}", txid)
    conn.execute("SELECT pg_advisory_lock(%s)", (key,))
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


def inspect(conn: Connection, shard: str, txid: UUID) -> tuple[str, str | None]:
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            """
            SELECT outcome, request_hash
            FROM participant_outcomes
            WHERE transaction_id = %s
            """,
            (txid,),
        ).fetchone()

        if row is not None:
            return row["outcome"], row["request_hash"]

        prepared = cursor.execute(
            "SELECT gid FROM pg_prepared_xacts WHERE gid LIKE %s LIMIT 2",
            (gid_prefix(shard, txid) + "%",),
        ).fetchall()

        if len(prepared) > 1:
            return "CONFLICT", None
        if prepared:
            return "PREPARED", prepared[0]["gid"]
        return "UNKNOWN", None
