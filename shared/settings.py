"""Validated environment settings for the three services."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

DEFAULT_SHARD_MAP = Path(__file__).resolve().parents[1] / "config/shard_map.json"


class ServiceSettings(BaseSettings):
    internal_api_token: str = ""

    def require_token(self) -> str:
        if not self.internal_api_token:
            raise RuntimeError("INTERNAL_API_TOKEN must be set")
        return self.internal_api_token


class DatabaseSettings(ServiceSettings):
    database_url: str = ""

    def require_database_url(self) -> str:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL must be set")
        return self.database_url


class BankingSettings(DatabaseSettings):
    shard_id: str = "A"
    replica_id: str = "A1"
    shard_start: int = Field(default=1, ge=1, le=9999)
    shard_end: int = Field(default=1000, ge=1, le=9999)


class GatewaySettings(ServiceSettings):
    shard_map_path: Path = DEFAULT_SHARD_MAP
    coordinator_url: str = "http://coordinator:8000"


class CoordinatorSettings(DatabaseSettings):
    shard_map_path: Path = DEFAULT_SHARD_MAP
