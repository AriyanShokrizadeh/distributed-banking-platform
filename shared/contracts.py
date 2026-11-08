"""Validated requests and stable fingerprints for idempotency."""

import hashlib
import json
from typing import Annotated, Any

from pydantic import BaseModel, Field

MAX_TRANSFER_AMOUNT = 1_000_000_000_000
MAX_BIGINT = 2**63 - 1
PositiveAmount = Annotated[int, Field(strict=True, gt=0, le=MAX_TRANSFER_AMOUNT)]


class AmountRequest(BaseModel):
    amount_minor: PositiveAmount


class TransferRequest(AmountRequest):
    source_account: str
    destination_account: str


def balance_limits(delta: int) -> tuple[int, int]:
    """Starting balance range for a nonnegative signed BIGINT update."""
    return max(0, -delta), MAX_BIGINT - max(0, delta)


def request_fingerprint(operation: str, payload: dict[str, Any]) -> str:
    """Canonical SHA-256 fingerprint; JSON encoding must stay stable."""
    encoded = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
