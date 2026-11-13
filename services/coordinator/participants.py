"""Communicate with the replicas of each 2PC participant."""

import logging
from typing import Any

import httpx

from shared.auth import internal_headers

logger = logging.getLogger("banking.coordinator")


class ParticipantClient:
    def __init__(self, endpoints: dict[str, list[str]], token: str) -> None:
        self.endpoints = endpoints
        self.client = httpx.Client(
            timeout=httpx.Timeout(22.0, connect=1.5),
            headers=internal_headers(token),
        )

    def close(self) -> None:
        self.client.close()

    def post(self, shard: str, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Try replicas in order; treat protocol conflicts as terminal responses."""
        for url in self.endpoints[shard]:
            try:
                response = self.client.post(url + path, json=payload)
                if response.status_code == 200:
                    return response.json()
                if response.status_code in (409, 422):
                    logger.error(
                        "Protocol conflict: shard=%s path=%s body=%s",
                        shard,
                        path,
                        response.text[:250],
                    )
                    return {"vote": "CONFLICT"}
                logger.warning("Participant %s returned HTTP %s", url, response.status_code)
            except (httpx.HTTPError, ValueError):
                logger.warning("Participant %s unavailable", url)
        return None
