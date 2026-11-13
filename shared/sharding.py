"""Shard-map validation and account routing."""

import re
from itertools import pairwise
from pathlib import Path
from typing import Self

from pydantic import AliasChoices, BaseModel, Field, model_validator

ACCOUNT_PATTERN = re.compile(r"A[0-9]{4}")


class ShardRouteError(ValueError):
    """An account ID is invalid or has no configured owner."""


def account_number(account_id: object) -> int:
    if not isinstance(account_id, str):
        raise ShardRouteError("Account ID must be a string")
    if not ACCOUNT_PATTERN.fullmatch(account_id):
        raise ShardRouteError("Account ID must look like A0500")
    return int(account_id[1:])


class ShardConfig(BaseModel):
    shard_id: str = Field(min_length=1, validation_alias=AliasChoices("shard_id", "id"))
    start: int = Field(ge=1, le=9999)
    end: int = Field(ge=1, le=9999)
    replicas: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.start > self.end:
            raise ValueError(f"Invalid shard range: {self.shard_id}")
        return self


class ShardMap(BaseModel):
    epoch: int = Field(ge=1)
    shards: tuple[ShardConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_shards(self) -> Self:
        shards = sorted(self.shards, key=lambda shard: shard.start)
        if len({shard.shard_id for shard in shards}) != len(shards):
            raise ValueError("Duplicate shard IDs")

        for first, second in pairwise(shards):
            if first.end >= second.start:
                raise ValueError(f"Overlapping shard ownership: {first.shard_id}/{second.shard_id}")
        self.shards = tuple(shards)
        return self

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        return cls.model_validate_json(Path(path).read_bytes())

    def owner(self, account_id: str) -> ShardConfig:
        number = account_number(account_id)
        for shard in self.shards:
            if shard.start <= number <= shard.end:
                return shard
        raise ShardRouteError(f"Account {account_id} is outside configured shard ranges")
