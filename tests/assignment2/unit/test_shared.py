"""Shared response handling, balance limits and internal authentication."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from shared.api import Result, as_response, internal_headers, require_internal
from shared.contracts import MAX_BIGINT, balance_limits


@pytest.mark.parametrize(
    "delta,expected",
    [
        (10, (0, MAX_BIGINT - 10)),
        (-10, (10, MAX_BIGINT)),
        (0, (0, MAX_BIGINT)),
    ],
)
def test_balance_bounds_prevent_overflow(delta, expected):
    assert balance_limits(delta) == expected


def test_valid_internal_token_is_accepted(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret")

    assert require_internal("secret") is None


@pytest.mark.parametrize("token", ["wrong", ""])
def test_invalid_internal_token_is_rejected(monkeypatch, token):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret")

    with pytest.raises(HTTPException) as error:
        require_internal(token)

    assert error.value.status_code == 403


def test_internal_headers_include_idempotency_key_when_provided():
    key = uuid4()

    assert internal_headers("secret", key) == {
        "X-Internal-Token": "secret",
        "Idempotency-Key": str(key),
    }


def test_internal_headers_without_idempotency_key():
    assert internal_headers("secret") == {"X-Internal-Token": "secret"}


def test_response_preserves_status_and_headers():
    response = as_response(Result(409, {"error": "collision"}), {"X-Shard-ID": "A"})

    assert response.status_code == 409
    assert response.headers["x-shard-id"] == "A"
