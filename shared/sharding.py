"""Validated shard configuration and account routing."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Self

from pydantic import AliasChoices, ConfigDict, Field, TypeAdapter, model_validator
from pydantic.dataclasses import dataclass as validated_dataclass

ACCOUNT_PATTERN = re.compile(r"A[0-9]{4}")


class ShardRouteError(ValueError):
    pass


def account_number(account_id: object) -> int:
    """Return the numeric part of an account such as A0500."""
    if not isinstance(account_id, str):
        raise ShardRouteError("Account ID must be a string")
    if not ACCOUNT_PATTERN.fullmatch(account_id):
        raise ShardRouteError("Account ID must look like A0500")
    return int(account_id[1:])


@dataclass(frozen=True)
class ShardConfig:
    shard_id: Annotated[str, Field(min_length=1, validation_alias=AliasChoices("shard_id", "id"))]
    start: Annotated[int, Field(ge=1, le=9999)]
    end: Annotated[int, Field(ge=1, le=9999)]
    replicas: Annotated[tuple[str, ...], Field(min_length=1)]


@validated_dataclass(config=ConfigDict(revalidate_instances="always"))
class ShardMap:
    epoch: Annotated[int, Field(ge=1)]
    shards: Annotated[Sequence[ShardConfig], Field(min_length=1)]

    @model_validator(mode="after")
    def check_shards(self) -> Self:
        self.shards = tuple(sorted(self.shards, key=lambda shard: shard.start))

        for shard in self.shards:
            if shard.start > shard.end:
                raise ValueError(f"Invalid shard range: {shard.shard_id}")

        if len({shard.shard_id for shard in self.shards}) != len(self.shards):
            raise ValueError("Duplicate shard IDs")

        for first, second in pairwise(self.shards):
            if first.end >= second.start:
                raise ValueError(f"Overlapping shard ownership: {first.shard_id}/{second.shard_id}")
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        return TypeAdapter(cls).validate_json(Path(path).read_bytes())

    def owner(self, account_id: str) -> ShardConfig:
        number = account_number(account_id)
        for shard in self.shards:
            if shard.start <= number <= shard.end:
                return shard
        raise ShardRouteError(f"Account {account_id} is outside configured shard ranges")
