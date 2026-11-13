"""2PC identifiers and messages are validated without a database."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared.two_phase import (
    DecisionMessage,
    PrepareMessage,
    advisory_key,
    gid_prefix,
    prepared_gid,
    transfer_hash,
)


def test_transfer_hash_is_stable_for_same_transfer():
    fingerprint = transfer_hash("A0500", "A1500", 300)

    assert fingerprint == transfer_hash("A0500", "A1500", 300)
    assert len(fingerprint) == 64


@pytest.mark.parametrize(
    "source,destination,amount",
    [("A0500", "A1500", 301), ("A1500", "A0500", 300)],
)
def test_transfer_hash_changes_with_transfer_details(source, destination, amount):
    assert transfer_hash("A0500", "A1500", 300) != transfer_hash(source, destination, amount)


def test_prepared_gid_contains_shard_and_transaction_identity():
    txid = uuid4()
    fingerprint = transfer_hash("A0500", "A1500", 300)

    gid = prepared_gid("A", txid, fingerprint)

    assert gid.startswith(gid_prefix("A", txid))
    assert len(gid.encode()) < 200
    assert gid != prepared_gid("B", txid, fingerprint)
    assert gid != prepared_gid("A", txid, transfer_hash("A0500", "A1500", 301))


@pytest.mark.parametrize("shard,fingerprint", [("A'; DROP TABLE accounts;--", "f" * 64), ("A", "x" * 64)])
def test_prepared_gid_rejects_untrusted_values(shard, fingerprint):
    with pytest.raises(ValueError):
        prepared_gid(shard, uuid4(), fingerprint)


@pytest.fixture
def prepare_fields():
    return {
        "transaction_id": uuid4(),
        "request_hash": "f" * 64,
        "account_id": "A0500",
        "operation": "DEBIT",
    }


def test_prepare_message_accepts_positive_integer_amount(prepare_fields):
    assert PrepareMessage(amount_minor=1, **prepare_fields).amount_minor == 1


@pytest.mark.parametrize("amount", [0, -3, 1.5, "10"])
def test_prepare_message_rejects_invalid_amount(prepare_fields, amount):
    with pytest.raises(ValidationError):
        PrepareMessage(amount_minor=amount, **prepare_fields)


def test_decision_message_accepts_valid_hash():
    txid = uuid4()

    assert DecisionMessage(transaction_id=txid, request_hash="0" * 64).transaction_id == txid


def test_decision_message_rejects_invalid_hash():
    with pytest.raises(ValidationError):
        DecisionMessage(transaction_id=uuid4(), request_hash="bad")


def test_advisory_key_is_stable_and_namespaced():
    txid = uuid4()
    key = advisory_key("participant-A", txid)

    assert key == advisory_key("participant-A", txid)
    assert key != advisory_key("coordinator", txid)
    assert -(2**63) <= key < 2**63
