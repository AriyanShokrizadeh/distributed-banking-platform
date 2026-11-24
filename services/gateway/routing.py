"""Thread-safe shard routing and periodic readiness checks."""

import threading

import httpx

from shared.sharding import ShardMap


class ReplicaRegistry:
    """Track readiness and round-robin positions independently per shard."""

    def __init__(self, shard_map: ShardMap) -> None:
        self._lock = threading.Lock()
        self.replicas = {shard.shard_id: shard.replicas for shard in shard_map.shards}
        self.health = {url: False for urls in self.replicas.values() for url in urls}
        self.next_index = dict.fromkeys(self.replicas, 0)

    def set_health(self, url: str, healthy: bool) -> None:
        with self._lock:
            if url not in self.health:
                raise ValueError(f"Unexpected replica: {url}")
            self.health[url] = healthy

    def candidates(self, shard_id: str) -> list[str]:
        """Rotate ready replicas; never spill traffic into another shard."""
        with self._lock:
            if shard_id not in self.replicas:
                raise ValueError(f"Unknown shard: {shard_id}")

            available = [url for url in self.replicas[shard_id] if self.health[url]]
            if not available:
                return []

            start = self.next_index[shard_id] % len(available)
            self.next_index[shard_id] += 1
            return available[start:] + available[:start]

    def snapshot(self) -> dict[str, dict[str, bool]]:
        with self._lock:
            return {
                shard: {url: self.health[url] for url in replicas}
                for shard, replicas in self.replicas.items()
            }


class HealthMonitor:
    """Mark replicas ready only when their database readiness probe passes."""

    def __init__(self, registry: ReplicaRegistry, client: httpx.Client, interval: float = 2) -> None:
        self.registry = registry
        self.client = client
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self.run, name="replica-health", daemon=True)

    def _is_ready(self, url: str) -> bool:
        """A failed probe never counts as a healthy banking replica."""
        try:
            response = self.client.get(f"{url}/health/ready", timeout=0.8)
        except httpx.RequestError:
            return False
        return response.status_code == 200

    def refresh(self) -> None:
        for replicas in self.registry.replicas.values():
            for url in replicas:
                self.registry.set_health(url, self._is_ready(url))

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            self.refresh()

    def start(self) -> None:
        self.refresh()
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join()
