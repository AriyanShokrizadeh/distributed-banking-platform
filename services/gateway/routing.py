"""Round-robin replica routing and periodic health checks."""

import threading

import httpx

from shared.sharding import ShardMap


class ReplicaRegistry:
    def __init__(self, shard_map: ShardMap) -> None:
        self.lock = threading.Lock()
        self.urls = {shard.shard_id: list(shard.replicas) for shard in shard_map.shards}
        self.healthy = {url: False for urls in self.urls.values() for url in urls}
        self.counter = dict.fromkeys(self.urls, 0)

    def set_health(self, url: str, healthy: bool) -> None:
        with self.lock:
            if url not in self.healthy:
                raise ValueError(f"Unexpected replica: {url}")
            self.healthy[url] = healthy

    def candidates(self, shard_id: str) -> list[str]:
        """Return healthy replicas in round-robin order within the requested shard."""
        with self.lock:
            if shard_id not in self.urls:
                raise ValueError(f"Unknown shard: {shard_id}")

            available = [url for url in self.urls[shard_id] if self.healthy[url]]
            if not available:
                return []

            index = self.counter[shard_id] % len(available)
            self.counter[shard_id] += 1
            return available[index:] + available[:index]

    def snapshot(self) -> dict[str, dict[str, bool]]:
        with self.lock:
            return {
                shard: {url: self.healthy[url] for url in replicas} for shard, replicas in self.urls.items()
            }


class HealthMonitor:
    def __init__(
        self,
        registry: ReplicaRegistry,
        client: httpx.Client,
        interval: float = 2,
    ) -> None:
        self.registry = registry
        self.client = client
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="replica-health", daemon=True)

    def refresh(self) -> None:
        """Check each replica and reuse the shared HTTP client."""
        for replicas in self.registry.urls.values():
            for url in replicas:
                try:
                    healthy = self.client.get(f"{url}/health/ready", timeout=0.8).status_code == 200
                except httpx.RequestError:
                    healthy = False
                self.registry.set_health(url, healthy)

    def run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.refresh()

    def start(self) -> None:
        self.refresh()
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join()
