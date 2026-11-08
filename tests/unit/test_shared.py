"""Pure validation and shared HTTP security behavior."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from shared.api import Result, as_response, internal_headers, require_internal
from shared.contracts import MAX_BIGINT, balance_limits


@pytest.mark.parametrize(
    "delta,lower,upper",
    [
        (10, 0, MAX_BIGINT - 10),
        (-10, 10, MAX_BIGINT),
        (0, 0, MAX_BIGINT),
    ],
)
def test_atomic_update_limits(delta: int, lower: int, upper: int) -> None:
    assert balance_limits(delta) == (lower, upper)


def test_internal_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "secret")
    assert require_internal("secret") is None
    for token in ("bad", ""):
        with pytest.raises(HTTPException) as error:
            require_internal(token)
        assert error.value.status_code == 403


def test_internal_headers_keep_request_identity() -> None:
    key = uuid4()
    assert internal_headers("secret", key) == {
        "X-Internal-Token": "secret",
        "Idempotency-Key": str(key),
    }
    assert internal_headers("secret") == {"X-Internal-Token": "secret"}


def test_result_response_preserves_status() -> None:
    response = as_response(Result(409, {"error": "collision"}), {"X-Shard-ID": "A"})
    assert response.status_code == 409
    assert response.headers["x-shard-id"] == "A"
