"""Pure protocol tests: no PostgreSQL or Docker needed."""

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


def test_same_transfer_has_same_hash_independent_of_retry():
    fingerprint = transfer_hash("A0500", "A1500", 300)
    assert fingerprint == transfer_hash("A0500", "A1500", 300)
    assert len(fingerprint) == 64
    assert fingerprint != transfer_hash("A0500", "A1500", 301)
    assert fingerprint != transfer_hash("A1500", "A0500", 300)


def test_prepared_gid_separates_shard_tx_and_fingerprint():
    txid = uuid4()
    fingerprint = transfer_hash("A0500", "A1500", 300)
    gid = prepared_gid("A", txid, fingerprint)
    assert gid.startswith(gid_prefix("A", txid))
    assert len(gid.encode()) < 200
    assert gid != prepared_gid("B", txid, fingerprint)
    assert gid != prepared_gid("A", txid, transfer_hash("A0500", "A1500", 301))


def test_prepared_gid_rejects_untrusted_strings():
    with pytest.raises(ValueError):
        prepared_gid("A'; DROP TABLE accounts;--", uuid4(), "f" * 64)
    with pytest.raises(ValueError):
        prepared_gid("A", uuid4(), "x" * 64)


def test_message_validation_prevents_negative_or_fractional_amount():
    attrs = {
        "transaction_id": uuid4(),
        "request_hash": "f" * 64,
        "account_id": "A0500",
        "operation": "DEBIT",
    }
    assert PrepareMessage(amount_minor=1, **attrs).amount_minor == 1
    for bad in [0, -3, 1.5, "10"]:
        with pytest.raises(ValidationError):
            PrepareMessage(amount_minor=bad, **attrs)


def test_decision_message_requires_uuid_and_sha256():
    txid = uuid4()
    assert DecisionMessage(transaction_id=txid, request_hash="0" * 64).transaction_id == txid
    with pytest.raises(ValidationError):
        DecisionMessage(transaction_id=txid, request_hash="bad")


def test_advisory_keys_stable_and_namespaced():
    txid = uuid4()
    assert advisory_key("participant-A", txid) == advisory_key("participant-A", txid)
    assert advisory_key("participant-A", txid) != advisory_key("coordinator", txid)
    assert -(2**63) <= advisory_key("participant-A", txid) < 2**63
