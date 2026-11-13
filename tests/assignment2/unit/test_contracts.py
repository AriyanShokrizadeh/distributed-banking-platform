"""Request validation and idempotency fingerprints."""

import pytest
from pydantic import ValidationError

from shared.contracts import AmountRequest, TransferRequest, request_fingerprint


def test_fingerprint_ignores_payload_field_order():
    first = {"source": "A0001", "amount": 5}
    reversed_fields = {"amount": 5, "source": "A0001"}

    assert request_fingerprint("TRANSFER", first) == request_fingerprint("TRANSFER", reversed_fields)


def test_fingerprint_changes_when_amount_changes():
    first = {"source": "A0001", "amount": 5}
    second = {"source": "A0001", "amount": 6}

    assert request_fingerprint("TRANSFER", first) != request_fingerprint("TRANSFER", second)


def test_fingerprint_includes_operation():
    payload = {"account_id": "A0001", "amount_minor": 5}

    assert request_fingerprint("DEPOSIT", payload) != request_fingerprint("WITHDRAW", payload)


@pytest.mark.parametrize("amount", [-1, 0, 0.2, True, "12", 1_000_000_000_001])
def test_amount_rejects_invalid_values(amount):
    with pytest.raises(ValidationError):
        AmountRequest(amount_minor=amount)


def test_transfer_accepts_positive_integer_amount():
    transfer = TransferRequest(
        source_account="A0001",
        destination_account="A1001",
        amount_minor=1,
    )

    assert transfer.amount_minor == 1
