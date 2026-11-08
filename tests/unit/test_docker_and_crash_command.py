"""Regression checks for the shared image and crash-recovery command."""

from pathlib import Path

import pytest

from scripts import common

ROOT = Path(__file__).resolve().parents[2]


def test_crash_demo_executes_psql(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_compose(*args: str) -> str:
        commands.append(args)
        return "1"

    monkeypatch.setattr(common, "compose", fake_compose)
    assert common.sql("db_a", "SELECT 1") == "1"
    assert commands[0][:4] == ("exec", "-T", "db_a", "psql")
