"""Healthy replica selection stays inside the requested shard."""

import httpx
import pytest

from services.gateway.routing import HealthMonitor, ReplicaRegistry
from shared.sharding import ShardConfig, ShardMap
from tests.common import mock_client


@pytest.fixture
def registry():
    mapping = ShardMap(
        epoch=1,
        shards=(
            ShardConfig(shard_id="A", start=1, end=1000, replicas=("a1", "a2")),
            ShardConfig(shard_id="B", start=1001, end=2000, replicas=("b1", "b2")),
        ),
    )
    return ReplicaRegistry(mapping)


def test_replicas_start_unhealthy(registry):
    assert registry.candidates("A") == []
    assert registry.snapshot()["A"] == {"a1": False, "a2": False}


def test_healthy_replicas_rotate_round_robin(registry):
    registry.set_health("a1", True)
    registry.set_health("a2", True)

    assert [registry.candidates("A")[0] for _ in range(4)] == ["a1", "a2", "a1", "a2"]


def test_unavailable_shard_does_not_fall_back_to_another_shard(registry):
    registry.set_health("b1", True)
    registry.set_health("b2", True)

    assert registry.candidates("A") == []
    assert registry.candidates("B") == ["b1", "b2"]


def test_failed_replica_is_excluded(registry):
    registry.set_health("a1", True)
    registry.set_health("a2", True)
    registry.set_health("a1", False)

    assert registry.candidates("A") == ["a2"]


def test_health_monitor_refreshes_all_replicas_with_same_client():
    mapping = ShardMap(
        epoch=1,
        shards=(
            ShardConfig(shard_id="A", start=1, end=1000, replicas=("http://a1", "http://a2")),
            ShardConfig(shard_id="B", start=1001, end=2000, replicas=("http://b1", "http://b2")),
        ),
    )
    registry = ReplicaRegistry(mapping)
    checked = []

    def handle(request):
        checked.append(request.url.host)
        return httpx.Response(503 if request.url.host == "a1" else 200)

    with mock_client(handle) as client:
        monitor = HealthMonitor(registry, client)
        monitor.refresh()
        monitor.refresh()

    assert registry.candidates("A") == ["http://a2"]
    assert registry.candidates("B") == ["http://b1", "http://b2"]
    assert checked == ["a1", "a2", "b1", "b2"] * 2
