"""Common request and response contracts for the HTTP APIs."""

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Header
from fastapi.responses import JSONResponse

from shared.auth import internal_headers as internal_headers, require_internal as require_internal

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
