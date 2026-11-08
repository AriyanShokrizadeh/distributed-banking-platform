"""HTTP helpers used by the banking services."""

import hmac
import os
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse

IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@dataclass(frozen=True, slots=True)
class Result:
    status_code: int
    body: dict[str, Any]


def error(code: str, message: str, status: int) -> Result:
    return Result(status, {"error": {"code": code, "message": message}})


def as_response(result: Result, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=result.status_code,
        content=result.body,
        headers=headers,
    )


def require_internal(token: str = Header(default="", alias="X-Internal-Token")) -> None:
    expected = os.getenv("INTERNAL_API_TOKEN", "")
    if not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(403, detail={"code": "INTERNAL_ONLY"})


def internal_headers(token: str, key: UUID | None = None) -> dict[str, str]:
    headers = {"X-Internal-Token": token}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    return headers
