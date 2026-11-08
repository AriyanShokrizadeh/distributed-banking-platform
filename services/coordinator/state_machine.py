"""Pure 2PC rules: no networking, database or background workers."""

from typing import Any, Mapping


def recovery_action(status: str, decision: str | None) -> str:
    if status == "COMPLETED":
        if decision not in ("COMMIT", "ABORT"):
            raise ValueError("COMPLETED needs a durable decision")
        return "DONE"
    if decision == "COMMIT":
        return "DRIVE_COMMIT"
    if decision == "ABORT":
        return "DRIVE_ABORT"
    if decision is not None:
        raise ValueError("Unknown decision")
    if status in ("INITIATED", "PREPARING"):
        return "PREPARE"
    if status == "PREPARED":
        return "DECIDE_COMMIT"
    raise ValueError(f"Invalid undecided state: {status}")


def assert_decision_not_reversed(existing: str | None, requested: str) -> None:
    if requested not in ("COMMIT", "ABORT"):
        raise ValueError("Invalid decision")
    if existing is not None and existing != requested:
        raise ValueError("A durable 2PC decision cannot be reversed")


def prepare_instruction(tx: Mapping[str, Any], shard: str) -> dict[str, Any]:
    """Build one participant's request: debit the source, credit the destination."""
    if shard not in (tx["source_shard"], tx["destination_shard"]):
        raise ValueError(f"Shard {shard} is not part of this transfer")

    is_source = shard == tx["source_shard"]
    return {
        "transaction_id": str(tx["transaction_id"]),
        "request_hash": tx["request_hash"],
        "account_id": tx["source_account"] if is_source else tx["destination_account"],
        "operation": "DEBIT" if is_source else "CREDIT",
        "amount_minor": tx["amount_minor"],
    }
