"""Docker Compose helpers build the expected database command."""

from scripts.assignment2 import compose as compose_helpers


def test_sql_runs_psql_in_requested_container(monkeypatch):
    commands = []

    def fake_compose(*args):
        commands.append(args)
        return "1"

    monkeypatch.setattr(compose_helpers, "compose", fake_compose)

    assert compose_helpers.sql("db_a", "SELECT 1") == "1"
    assert commands[0][:4] == ("exec", "-T", "db_a", "psql")
