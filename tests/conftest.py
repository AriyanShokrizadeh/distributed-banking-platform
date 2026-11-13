"""HTTP client for integration tests that require a running Gateway."""

import os

import httpx
import pytest


@pytest.fixture(scope="module")
def client():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 to run integration tests")

    gateway_url = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=gateway_url, timeout=30) as session:
        assert session.get("/health/ready", timeout=4).status_code == 200
        yield session
