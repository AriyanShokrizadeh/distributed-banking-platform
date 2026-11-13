"""Fast structural checks; no VM or Kubernetes access required."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATABASES = ("db-a", "db-b", "db-coordinator")


def patch(folder: str, name: str) -> dict[str, object]:
    data = json.loads((ROOT / folder / "patches" / name).read_text())
    return {item["path"]: item["value"] for item in data}


def test_database_replication_and_two_worker_spread() -> None:
    for cluster in DATABASES:
        settings = patch("k8s/bonus1", f"{cluster}.json")
        assert settings["/spec/postgresql/synchronous/number"] == 2
        assert settings["/spec/affinity/nodeSelector"] == {"banking-worker": "true"}
        assert settings["/spec/storage/storageClass"] == "local-path"
        constraint = settings["/spec/topologySpreadConstraints"][0]
        assert constraint["minDomains"] == 2
        assert constraint["maxSkew"] == 1
        assert constraint["whenUnsatisfiable"] == "DoNotSchedule"
        assert constraint["labelSelector"]["matchLabels"] == {"cnpg.io/cluster": cluster}


def test_banking_replicas_spread_between_workers() -> None:
    for app in ("bank-a", "bank-b", "gateway"):
        settings = patch("k8s/bonus1", f"{app}.json")
        constraint = settings["/spec/template/spec/topologySpreadConstraints"][0]
        assert constraint["minDomains"] == 2
        assert constraint["labelSelector"]["matchLabels"] == {"app": app}
    assert patch("k8s/bonus1", "gateway.json")["/spec/replicas"] == 2


def test_backup_targets_are_separate() -> None:
    manifest = (ROOT / "k8s/bonus2/objectstores.yaml").read_text()
    for db in DATABASES:
        assert f"s3://YOUR_BUCKET/{db}/" in manifest
        plugin = patch("k8s/bonus2", f"{db}-backup.json")
        assert plugin["/spec/plugins"][0]["parameters"]["barmanObjectName"] == f"{db}-store"


def test_control_plane_restore_has_safety_guards() -> None:
    restore = (ROOT / "scripts/bonus/control_plane_restore.sh").read_text()
    assert "BONUS_RESTORE_CONFIRM" in restore
    assert "--bump-revision 1000000000 --mark-compacted" in restore
    assert "[[ ! -d /etc/kubernetes" in restore
    assert "! -d /var/lib/etcd/member" in restore
    assert "rm -rf /var/lib/etcd" not in restore


def test_backup_requires_external_mount_and_encryption() -> None:
    backup = (ROOT / "scripts/bonus/control_plane_backup.sh").read_text()
    assert 'mountpoint -q "$backup_dir"' in backup
    assert "openssl enc -aes-256-cbc -pbkdf2 -salt" in backup
    assert 'snapshot save "$snapshot"' in backup
