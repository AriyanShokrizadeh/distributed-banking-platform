"""Bounded recovery of unfinished 2PC transfers.

The database owns transaction state; this worker only schedules attempts.
"""

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import UUID

from shared.observability import RECOVERY_FAILURES
from services.coordinator import store
from services.coordinator.protocol import TwoPhaseProtocol
from services.coordinator.store import DatabasePool

logger = logging.getLogger("banking.coordinator")


class Engine:
    """Schedule pending transactions; the protocol handles their decisions."""

    def __init__(
        self,
        pool: DatabasePool,
        endpoints: dict[str, list[str]],
        token: str,
        workers: int = 8,
        poll_interval: float = 0.5,
    ) -> None:
        self.pool = pool
        self.workers = workers
        self.poll_interval = poll_interval
        self.protocol = TwoPhaseProtocol(pool, endpoints, token)
        self.executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="2pc",
        )
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.lock = threading.Lock()
        self.inflight: set[UUID] = set()
        self.cooldown: dict[UUID, float] = {}
        self.thread = threading.Thread(target=self.run, name="2pc-recovery", daemon=True)

    def start(self) -> None:
        self.thread.start()
        self.wake()

    def stop(self) -> None:
        self.stop_event.set()
        self.wake()
        self.thread.join()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.protocol.close()

    def wake(self) -> None:
        self.wake_event.set()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.schedule_pending()
            except Exception:
                logger.exception("Coordinator scan failed; retrying")
            self.wake_event.wait(self.poll_interval)
            self.wake_event.clear()

    def _submit(self, txid: UUID) -> None:
        """Submit reserved work, releasing its slot if submission fails."""
        try:
            future = self.executor.submit(self.protocol.resolve, txid)
        except Exception:
            with self.lock:
                self.inflight.discard(txid)
            raise
        future.add_done_callback(lambda task, tid=txid: self.finish(tid, task))

    def schedule_pending(self) -> None:
        """Schedule durable unfinished transactions within the worker limit."""
        now = time.monotonic()
        with self.lock:
            self.cooldown = {
                txid: expires_at for txid, expires_at in self.cooldown.items() if expires_at > now
            }

        for txid in store.pending_ids(self.pool):
            with self.lock:
                if len(self.inflight) >= self.workers:
                    break
                if txid in self.inflight or txid in self.cooldown:
                    continue
                self.inflight.add(txid)

            self._submit(txid)

    def finish(self, txid: UUID, future: Future[None]) -> None:
        try:
            future.result()
        except Exception:
            RECOVERY_FAILURES.inc()
            logger.exception("Failed to resolve transaction %s", txid)
        finally:
            with self.lock:
                self.inflight.discard(txid)
                self.cooldown[txid] = time.monotonic() + 1.5
