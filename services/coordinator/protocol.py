"""Two-phase commit protocol: prepare, persist a decision, and finish/recover.

The database stores every decision *before* the coordinator sends commit/abort
messages, so an interrupted transaction can safely be resumed.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import httpx

from services.coordinator import store
from services.coordinator.state_machine import prepare_instruction, recovery_action
from services.coordinator.store import DatabasePool
from shared.two_phase import advisory_key

logger = logging.getLogger("banking.coordinator")


class TwoPhaseProtocol:
    def __init__(self, pool: DatabasePool, endpoints: dict[str, list[str]], token: str):
        self.pool = pool
        self.endpoints = endpoints
        self.client = httpx.Client(
            timeout=httpx.Timeout(22.0, connect=1.5),
            headers={"X-Internal-Token": token},
        )

    def close(self) -> None:
        self.client.close()

    @contextmanager
    def transaction_lock(self, txid: UUID) -> Generator[bool]:
        """Only one coordinator replica may recover a transaction at a time."""
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

    def post(self, shard: str, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Try replicas in order; treat protocol conflicts as terminal responses."""
        for url in self.endpoints[shard]:
            try:
                response = self.client.post(url + path, json=payload)
                if response.status_code == 200:
                    return response.json()
                if response.status_code in (409, 422):
                    logger.error(
                        "Protocol conflict: shard=%s path=%s body=%s",
                        shard,
                        path,
                        response.text[:250],
                    )
                    return {"vote": "CONFLICT"}
                logger.warning("Participant %s returned HTTP %s", url, response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.warning("Participant %s unavailable", url)
        return None

    def fault_once(self, label: str) -> None:
        """Demo-only: crash once after writing a durable recovery checkpoint."""
        if os.getenv(label) == "1" and store.first_fault(self.pool, label):
            os._exit(71)

    def resolve(self, txid: UUID) -> None:
        """Advance one transaction from its *persisted* state, including after crashes."""
        with self.transaction_lock(txid) as acquired:
            if not acquired:
                return
            tx = store.get_transaction(self.pool, txid)
            if tx is None:
                return

            action = recovery_action(tx["status"], tx["decision"])
            if action == "DONE":
                return
            if action in ("DRIVE_COMMIT", "DRIVE_ABORT"):
                self.complete_decided(tx)
                return
            if action == "DECIDE_COMMIT":
                self.decide_commit(txid)
            else:
                self.prepare(tx)

            decided = store.get_transaction(self.pool, txid)
            if decided is not None and decided["decision"] is not None:
                self.complete_decided(decided)

    def prepare(self, tx: dict[str, Any]) -> None:
        """Ask both participants to prepare; commit only after both vote YES."""
        txid = tx["transaction_id"]
        store.set_status(self.pool, txid, "PREPARING")

        for shard in sorted((tx["source_shard"], tx["destination_shard"])):
            reply = self.post(shard, "/internal/2pc/prepare", prepare_instruction(tx, shard))
            if reply is None or reply.get("vote") != "YES":
                store.record_decision(self.pool, txid, "ABORT")
                return
            store.record_prepare_ack(self.pool, txid, shard)

        store.set_status(self.pool, txid, "PREPARED")
        self.fault_once("CRASH_AFTER_PREPARED_ONCE")
        self.decide_commit(txid)

    def decide_commit(self, txid: UUID) -> None:
        """Persist COMMIT before sending it; retry safely after a crash."""
        store.record_decision(self.pool, txid, "COMMIT")
        self.fault_once("CRASH_AFTER_COMMIT_ONCE")

    def complete_decided(self, tx: dict[str, Any]) -> None:
        """Retry an already durable decision until all participants acknowledge."""
        decision = tx["decision"]
        expected_state = {"COMMIT": "COMMITTED", "ABORT": "ABORTED"}.get(decision)
        if expected_state is None:
            raise ValueError("Transaction has no final decision")

        path = f"/internal/2pc/{decision.lower()}"
        txid = tx["transaction_id"]
        payload = {"transaction_id": str(txid), "request_hash": tx["request_hash"]}

        for participant in tx["participants"]:
            if participant["decision_ack_at"]:
                continue
            shard = participant["shard_id"]
            reply = self.post(shard, path, payload)
            if reply and reply.get("vote") == "ACK" and reply.get("state") == expected_state:
                store.record_decision_ack(self.pool, txid, shard)

        store.complete_if_all_acknowledged(self.pool, txid)
