import httpx

from services.gateway.routing import HealthMonitor, ReplicaRegistry
from shared.sharding import ShardConfig, ShardMap


def make_registry():
    mapping = ShardMap(
        1,
        [
            ShardConfig("A", 1, 1000, ("a1", "a2")),
            ShardConfig("B", 1001, 2000, ("b1", "b2")),
        ],
    )
    return ReplicaRegistry(mapping)


def test_replica_round_robin_and_no_cross_shard_fallback():
    registry = make_registry()
    for replica in ("a1", "a2", "b1", "b2"):
        registry.set_health(replica, True)
    assert [registry.candidates("A")[0] for _ in range(4)] == ["a1", "a2", "a1", "a2"]
    registry.set_health("a1", False)
    assert registry.candidates("A") == ["a2"]
    registry.set_health("a2", False)
    assert registry.candidates("A") == []
    assert registry.candidates("B")[0] in ("b1", "b2")


def test_initially_unhealthy_and_snapshot():
    registry = make_registry()
    assert registry.candidates("A") == []
    assert registry.snapshot()["A"]["a1"] is False


def test_health_monitor_reuses_client() -> None:
    mapping = ShardMap(
        1,
        [
            ShardConfig("A", 1, 1000, ("http://a1", "http://a2")),
            ShardConfig("B", 1001, 2000, ("http://b1", "http://b2")),
        ],
    )
    registry = ReplicaRegistry(mapping)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host or "")
        status = 503 if request.url.host == "a1" else 200
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monitor = HealthMonitor(registry, client)
        monitor.refresh()
        assert registry.candidates("A") == ["http://a2"]
        assert registry.candidates("B") == ["http://b1", "http://b2"]
        monitor.refresh()

    assert seen == ["a1", "a2", "b1", "b2"] * 2
