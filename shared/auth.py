"""Token authentication and headers for internal service calls."""

import hmac
import os
from uuid import UUID

from fastapi import Header, HTTPException


def require_internal(token: str = Header(default="", alias="X-Internal-Token")) -> None:
    expected = os.getenv("INTERNAL_API_TOKEN", "")
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(403, detail={"code": "INTERNAL_ONLY"})


def internal_headers(token: str, key: UUID | None = None) -> dict[str, str]:
    headers = {"X-Internal-Token": token}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    return headers
