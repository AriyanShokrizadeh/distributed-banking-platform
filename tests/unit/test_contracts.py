import pytest
from pydantic import ValidationError
from shared.contracts import AmountRequest, TransferRequest, request_fingerprint


def test_canonical_hash_is_order_independent():
    a = request_fingerprint("TRANSFER", {"source": "A0001", "amount": 5})
    b = request_fingerprint("TRANSFER", {"amount": 5, "source": "A0001"})
    assert a == b
    assert a != request_fingerprint("TRANSFER", {"amount": 6, "source": "A0001"})


@pytest.mark.parametrize("invalid", [-1, 0, 0.2, True, "12", 1_000_000_000_001])
def test_invalid_amounts(invalid):
    with pytest.raises(ValidationError):
        AmountRequest(amount_minor=invalid)


def test_operation_changes_request_fingerprint():
    payload = {"account_id": "A0001", "amount_minor": 5}
    assert request_fingerprint("DEPOSIT", payload) != request_fingerprint("WITHDRAW", payload)


def test_transfer_request_requires_positive_amount():
    request = TransferRequest(source_account="A0001", destination_account="A1001", amount_minor=1)
    assert request.amount_minor == 1
