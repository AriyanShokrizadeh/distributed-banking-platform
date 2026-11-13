"""Small HTTP helpers shared by unit and integration tests."""

from concurrent.futures import ThreadPoolExecutor

import httpx


def mock_client(handler):
    return httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))


def submit_transfer(client, source, destination, amount, key=None):
    from scripts.common import transfer

    response = transfer(client, source, destination, amount, key)
    assert response.status_code in (200, 202), response.text
    return response.json()


def wait_for_transaction(client, txid, timeout=45):
    from scripts.common import wait_for_transaction as poll

    return poll(client, txid, timeout)


def parallel_posts(client, path, amount, count, workers):
    from scripts.common import post

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda _: post(client, path, {"amount_minor": amount}), range(count)))
