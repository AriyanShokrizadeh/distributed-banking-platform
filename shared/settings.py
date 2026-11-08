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


class BankingSettings(ServiceSettings):
    shard_id: str = "A"
    replica_id: str = "A1"
    shard_start: int = Field(default=1, ge=1, le=9999)
    shard_end: int = Field(default=1000, ge=1, le=9999)
    database_url: str = "postgresql://banking:banking@localhost:5432/banking"


class GatewaySettings(ServiceSettings):
    shard_map_path: Path = DEFAULT_SHARD_MAP
    coordinator_url: str = "http://coordinator:8000"


class CoordinatorSettings(ServiceSettings):
    shard_map_path: Path = DEFAULT_SHARD_MAP
    database_url: str = ""
