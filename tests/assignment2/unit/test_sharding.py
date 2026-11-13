"""Shard configuration and account ownership."""

from pathlib import Path

import pytest

from shared.sharding import ShardConfig, ShardMap, ShardRouteError, account_number

SHARD_MAP_FILE = Path(__file__).resolve().parents[3] / "config/shard_map.json"


def shard(shard_id, start, end, replicas=("http://bank:8000",)):
    return ShardConfig(shard_id=shard_id, start=start, end=end, replicas=replicas)


@pytest.fixture(scope="module")
def shard_map():
    return ShardMap.from_file(SHARD_MAP_FILE)


@pytest.mark.parametrize(
    "account,expected_shard",
    [("A0001", "A"), ("A1000", "A"), ("A1001", "B"), ("A2000", "B")],
)
def test_account_routes_to_correct_shard(shard_map, account, expected_shard):
    assert shard_map.owner(account).shard_id == expected_shard


@pytest.mark.parametrize("account", ["B0001", "A2001", "A0000", "A00001", "A-001", "a0500"])
def test_invalid_or_unmapped_accounts_are_rejected(shard_map, account):
    with pytest.raises(ShardRouteError):
        shard_map.owner(account)


def test_overlapping_ranges_are_rejected():
    with pytest.raises(ValueError, match="Overlapping"):
        ShardMap(epoch=1, shards=(shard("A", 1, 1000), shard("B", 900, 2000)))


def test_account_id_is_converted_to_number():
    assert account_number("A0500") == 500


def test_duplicate_shard_ids_are_rejected():
    with pytest.raises(ValueError):
        ShardMap(epoch=1, shards=(shard("A", 1, 100), shard("A", 101, 200)))


@pytest.mark.parametrize(
    "start,end,replicas",
    [(1, 0, ("a",)), (1, 100, ())],
)
def test_invalid_shard_definition_is_rejected(start, end, replicas):
    with pytest.raises(ValueError):
        shard("A", start, end, replicas)


def test_shard_map_normalizes_replica_collections():
    config = shard("A", 1, 1000, ("a1", "a2"))
    from_list = ShardMap.model_validate({"epoch": 1, "shards": [config]})
    from_tuple = ShardMap(epoch=1, shards=(config,))

    assert from_list.shards == from_tuple.shards
    assert isinstance(from_list.shards, tuple)
    assert from_list.owner("A0500") == from_tuple.owner("A0500")
