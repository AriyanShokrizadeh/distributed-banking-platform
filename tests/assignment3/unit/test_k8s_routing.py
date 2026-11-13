"""Kubernetes routes through the service of the owning shard."""

from pathlib import Path

from services.gateway.routing import ReplicaRegistry
from shared.sharding import ShardMap

SHARD_MAP_FILE = Path(__file__).resolve().parents[3] / "config/shard_map.k8s.json"


def test_kubernetes_routes_to_owning_shard_service():
    mapping = ShardMap.from_file(SHARD_MAP_FILE)
    registry = ReplicaRegistry(mapping)
    registry.set_health("http://bank-a:8000", True)
    registry.set_health("http://bank-b:8000", True)

    assert mapping.owner("A0500").shard_id == "A"
    assert mapping.owner("A1500").shard_id == "B"
    assert registry.candidates("A") == ["http://bank-a:8000"]
    assert registry.candidates("B") == ["http://bank-b:8000"]


def test_unhealthy_shard_does_not_affect_other_shard():
    mapping = ShardMap.from_file(SHARD_MAP_FILE)
    registry = ReplicaRegistry(mapping)
    registry.set_health("http://bank-a:8000", True)
    registry.set_health("http://bank-b:8000", True)

    registry.set_health("http://bank-a:8000", False)

    assert registry.candidates("A") == []
    assert registry.candidates("B") == ["http://bank-b:8000"]
