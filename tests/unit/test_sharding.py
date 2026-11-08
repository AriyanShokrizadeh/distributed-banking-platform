import pytest
from pathlib import Path
from shared.sharding import ShardConfig, ShardMap, ShardRouteError, account_number

MAP = Path(__file__).resolve().parents[2] / "config/shard_map.json"


def test_routing_boundaries():
    mapping = ShardMap.from_file(MAP)
    assert mapping.owner("A0001").shard_id == "A"
    assert mapping.owner("A1000").shard_id == "A"
    assert mapping.owner("A1001").shard_id == "B"
    assert mapping.owner("A2000").shard_id == "B"


@pytest.mark.parametrize("account", ["B0001", "A2001", "A0000", "A00001", "A-001", "a0500"])
def test_invalid_or_out_of_range_accounts_are_rejected(account):
    with pytest.raises(ShardRouteError):
        ShardMap.from_file(MAP).owner(account)


def test_overlap_is_rejected():
    with pytest.raises(ValueError, match="Overlapping"):
        ShardMap(
            1,
            [
                ShardConfig("A", 1, 1000, ("one",)),
                ShardConfig("B", 900, 2000, ("two",)),
            ],
        )


def test_account_numeric_parsing():
    assert account_number("A0500") == 500


@pytest.mark.parametrize(
    "shards",
    [
        [ShardConfig("A", 1, 100, ("a",)), ShardConfig("A", 101, 200, ("b",))],
        [ShardConfig("A", 1, 0, ("a",))],
        [ShardConfig("A", 1, 100, ())],
    ],
)
def test_invalid_shard_configuration(shards):
    with pytest.raises(ValueError):
        ShardMap(1, shards)


def test_shard_map_accepts_lists_and_tuples() -> None:
    shard = ShardConfig("A", 1, 1000, ("a1", "a2"))
    from_list = ShardMap(1, [shard])
    from_tuple = ShardMap(1, (shard,))

    assert isinstance(from_list.shards, tuple)
    assert isinstance(from_tuple.shards, tuple)
    assert from_list.owner("A0500") == from_tuple.owner("A0500")
