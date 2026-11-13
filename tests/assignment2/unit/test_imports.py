"""Public experiment helper functions remain importable."""

from pathlib import Path

from scripts import common
from scripts.assignment2 import compose


def test_shared_script_helpers_are_available():
    assert isinstance(common.ROOT, Path)
    assert callable(common.transfer)
    assert callable(common.wait_for_transaction)


def test_compose_helpers_are_available():
    assert callable(compose.docker)
    assert callable(compose.compose)
    assert callable(compose.sql)
    assert callable(compose.total_money)
