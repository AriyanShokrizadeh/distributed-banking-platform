"""Cluster helpers select the CloudNativePG primary for SQL commands."""

import json

from scripts.assignment3 import cluster


def test_primary_uses_cloudnativepg_primary_label(monkeypatch):
    commands = []

    def fake_kubectl(*args):
        commands.append(args)
        return json.dumps({"items": [{"metadata": {"name": "db-a-2"}}]})

    monkeypatch.setattr(cluster, "kubectl", fake_kubectl)

    assert cluster.primary("db-a") == "db-a-2"
    assert "cnpg.io/cluster=db-a,cnpg.io/instanceRole=primary" in commands[0]


def test_sql_runs_on_coordinator_primary(monkeypatch):
    commands = []
    monkeypatch.setattr(cluster, "primary", lambda _cluster: "db-coordinator-1")

    def fake_kubectl(*args, **kwargs):
        commands.append((args, kwargs))
        return "1"

    monkeypatch.setattr(cluster, "kubectl", fake_kubectl)

    assert cluster.sql("db-coordinator", "SELECT 1") == "1"
    args, kwargs = commands[0]
    assert args[-3:] == ("-tA", "-c", "SELECT 1")
    assert "coordinator" in args
    assert "db-coordinator-1" in args
    assert kwargs["timeout"] == 60
