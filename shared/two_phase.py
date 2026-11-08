"""2PC messages, transaction fingerprints, and PostgreSQL lock identifiers."""

import hashlib
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from shared.contracts import PositiveAmount, request_fingerprint

RequestHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PrepareMessage(BaseModel):
    transaction_id: UUID
    request_hash: RequestHash
    account_id: str
    operation: Literal["DEBIT", "CREDIT"]
    amount_minor: PositiveAmount


class DecisionMessage(BaseModel):
    transaction_id: UUID
    request_hash: RequestHash


def transfer_hash(source: str, destination: str, amount_minor: int) -> str:
    return request_fingerprint(
        "CROSS_SHARD_TRANSFER",
        {
            "source_account": source,
            "destination_account": destination,
            "amount_minor": amount_minor,
        },
    )


def prepared_gid(shard: str, txid: UUID, fingerprint: str) -> str:
    if shard not in {"A", "B", "C"}:
        raise ValueError("Unsupported shard")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid fingerprint")
    return f"bank:{shard}:{txid}:{fingerprint[:24]}"


def gid_prefix(shard: str, txid: UUID) -> str:
    return f"bank:{shard}:{txid}:"


def advisory_key(namespace: str, transaction_id: UUID) -> int:
    digest = hashlib.sha256(f"{namespace}:{transaction_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)
