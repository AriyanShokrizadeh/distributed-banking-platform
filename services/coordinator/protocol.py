"""Durable two-phase commit protocol and crash recovery.

A decision is committed to the Coordinator database *before* sending COMMIT or
ABORT to participants. Replayed messages are safe after a process restart.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from services.coordinator import store
from services.coordinator.participants import ParticipantClient
from services.coordinator.state_machine import prepare_instruction, recovery_action
from services.coordinator.store import DatabasePool
from shared.two_phase import DECISION_OUTCOME, advisory_key


class TwoPhaseProtocol:
    """Resolve the persisted state of a transaction one step at a time."""

    def __init__(self, pool: DatabasePool, endpoints: dict[str, list[str]], token: str) -> None:
        self.pool = pool
        self.participants = ParticipantClient(endpoints, token)

    def close(self) -> None:
        self.participants.close()

    @contextmanager
    def transaction_lock(self, txid: UUID) -> Generator[bool, None, None]:
        """Prevent two Coordinator instances from resolving the same ID."""
        with self.pool.connection() as conn:
            key = advisory_key("coordinator", txid)
            row = conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()
            if row is None:
                raise RuntimeError("Failed to acquire transaction lock")

            acquired = bool(row[0])
            try:
                yield acquired
            finally:
                if acquired:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (key,))

    def fault_once(self, label: str) -> None:
        """Demo-only: exit once after a durable recovery checkpoint."""
        if os.getenv(label) == "1" and store.first_fault(self.pool, label):
            os._exit(71)

    def resolve(self, txid: UUID) -> None:
        """Continue from saved state; never assume an HTTP request succeeded."""
        with self.transaction_lock(txid) as acquired:
            if not acquired:
                return
            transaction = store.get_transaction(self.pool, txid)
            if transaction is None:
                return

            action = recovery_action(transaction["status"], transaction["decision"])
            if action == "DONE":
                return
            if action in ("DRIVE_COMMIT", "DRIVE_ABORT"):
                self.complete_decided(transaction)
                return
            if action == "DECIDE_COMMIT":
                self.decide_commit(txid)
            else:
                self.prepare(transaction)

            # Re-read persisted state rather than relying on the outcome of a network call.
            decided = store.get_transaction(self.pool, txid)
            if decided is not None and decided["decision"] is not None:
                self.complete_decided(decided)

    def _collect_prepare_votes(self, transaction: dict[str, Any]) -> bool:
        """Persist each YES vote; stop immediately on a NO or uncertain reply."""
        txid = transaction["transaction_id"]
        shards = sorted((transaction["source_shard"], transaction["destination_shard"]))

        for shard in shards:
            instruction = prepare_instruction(transaction, shard)
            reply = self.participants.post(shard, "/internal/2pc/prepare", instruction)
            if reply is None or reply.get("vote") != "YES":
                return False
            store.record_prepare_ack(self.pool, txid, shard)
        return True

    def prepare(self, transaction: dict[str, Any]) -> None:
        """Collect both YES votes; otherwise durably decide ABORT."""
        txid = transaction["transaction_id"]
        store.set_status(self.pool, txid, "PREPARING")

        if not self._collect_prepare_votes(transaction):
            store.record_decision(self.pool, txid, "ABORT")
            return

        store.set_status(self.pool, txid, "PREPARED")
        self.fault_once("CRASH_AFTER_PREPARED_ONCE")
        self.decide_commit(txid)

    def decide_commit(self, txid: UUID) -> None:
        """Persist COMMIT before notifying any participant."""
        store.record_decision(self.pool, txid, "COMMIT")
        self.fault_once("CRASH_AFTER_COMMIT_ONCE")

    def complete_decided(self, transaction: dict[str, Any]) -> None:
        """Replay a durable COMMIT/ABORT until both participants acknowledge."""
        decision = transaction["decision"]
        expected = DECISION_OUTCOME.get(decision)
        if expected is None:
            raise ValueError("Transaction has no final decision")

        txid = transaction["transaction_id"]
        path = f"/internal/2pc/{decision.lower()}"
        payload = {
            "transaction_id": str(txid),
            "request_hash": transaction["request_hash"],
        }

        for participant in transaction["participants"]:
            if participant["decision_ack_at"]:
                continue
            shard = participant["shard_id"]
            reply = self.participants.post(shard, path, payload)
            if reply and reply.get("vote") == "ACK" and reply.get("state") == expected:
                store.record_decision_ack(self.pool, txid, shard)

        store.complete_if_all_acknowledged(self.pool, txid)
