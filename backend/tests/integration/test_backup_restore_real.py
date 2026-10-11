"""Real backups with the real dump tools, restored into the same server and compared.

Requires the dump tools on the host: backend/scripts/install-dump-tools.sh
(or MBP_REAL_MYSQLDUMP_PATH / MBP_REAL_MARIADB_DUMP_PATH pointing at them).
"""

import bz2
import gzip
import subprocess

import pytest

from tests.conftest import BACKUP_ROOT, wait_for_run
from tests.integration.conftest import ROOT_PASSWORD

pytestmark = pytest.mark.integration

SEED = [
    "DROP DATABASE IF EXISTS seeded",
    "DROP DATABASE IF EXISTS restored",
    "CREATE DATABASE seeded CHARACTER SET utf8mb4",
    "CREATE DATABASE restored CHARACTER SET utf8mb4",
    """CREATE TABLE seeded.items (
         id INT PRIMARY KEY, name VARCHAR(100), payload BLOB, price DECIMAL(10,2)
       ) ENGINE=InnoDB""",
    """INSERT INTO seeded.items VALUES
         (1, 'سلام دنیا', X'00FF10A0', 12.50),
         (2, 'emoji 🔐 & "quotes"', NULL, 0.01),
         (3, 'back\\\\slash', X'DEADBEEF', 999.99)""",
    # Objects created without a schema prefix, as usual. (MariaDB keeps a trigger's original
    # text, so a schema-qualified trigger would be recreated in its original schema.)
    "USE seeded",
    "CREATE VIEW cheap AS SELECT id, name FROM items WHERE price < 20",
    "CREATE PROCEDURE count_items() SELECT COUNT(*) FROM items",
    "CREATE TRIGGER items_bi BEFORE INSERT ON items FOR EACH ROW SET NEW.name = TRIM(NEW.name)",
    "CREATE EVENT nightly ON SCHEDULE EVERY 1 DAY DO DELETE FROM items WHERE 0",
    # Least-privilege backup user from the README (without PROCESS, see research §3).
    "DROP USER IF EXISTS 'mbp_backup'@'%'",
    "CREATE USER 'mbp_backup'@'%' IDENTIFIED BY 'Backup-Pass-1'",
    "GRANT SELECT, SHOW VIEW, TRIGGER, EVENT, LOCK TABLES ON *.* TO 'mbp_backup'@'%'",
]


def scalar(server, sql):
    conn = server.admin_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchone()
    finally:
        conn.close()


def restore(server, dump: bytes):
    client = "mariadb" if server.kind == "mariadb" else "mysql"
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            server.container_id,
            client,
            "-uroot",
            f"-p{ROOT_PASSWORD}",
            "restored",
        ],
        input=dump,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def object_counts(server, schema):
    return scalar(
        server,
        f"""SELECT
          (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='{schema}'),
          (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='{schema}'),
          (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA='{schema}'),
          (SELECT COUNT(*) FROM information_schema.VIEWS WHERE TABLE_SCHEMA='{schema}')""",
    )


@pytest.mark.parametrize("compression", ["gzip", "bzip2", "none"])
def test_backup_restores_identically(auth_client, server, real_tools, compression):
    server.execute(*SEED)
    instance = auth_client.post(
        "/api/instances",
        json={
            "name": f"{server.kind}-{compression}",
            "host": server.host,
            "port": server.port,
            "username": "mbp_backup",
            "password": "Backup-Pass-1",
        },
    ).json()
    auth_client.put(
        f"/api/instances/{instance['id']}/backup-settings",
        json={"storage_dir": None, "name_pattern": None, "compression": compression},
    )
    run_id = auth_client.post(
        f"/api/instances/{instance['id']}/backups",
        json={"scope": "single", "database": "seeded"},
    ).json()["created"][0]["id"]
    run = wait_for_run(auth_client, run_id, timeout=120)
    assert run["status"] == "success", run
    assert run["server_type"] == server.kind

    path = next(BACKUP_ROOT.rglob(run["file_name"]))
    raw = path.read_bytes()
    dump = {"gzip": gzip.decompress, "bzip2": bz2.decompress, "none": bytes}[compression](raw)
    assert b"-- Dump completed" in dump[-200:]
    assert b"Backup-Pass-1" not in dump

    restore(server, dump)
    assert (
        scalar(server, "CHECKSUM TABLE restored.items")[1]
        == scalar(server, "CHECKSUM TABLE seeded.items")[1]
    )
    assert scalar(server, "SELECT name FROM restored.items WHERE id = 1")[0] == "سلام دنیا"
    assert object_counts(server, "restored") == object_counts(server, "seeded") == (1, 1, 1, 1)


def test_least_privilege_user_without_process_privilege(auth_client, server, real_tools):
    """The README grants (minus PROCESS) are enough for a backup."""
    server.execute(*SEED)
    instance_id = auth_client.post(
        "/api/instances",
        json={
            "name": f"{server.kind}-lp",
            "host": server.host,
            "port": server.port,
            "username": "mbp_backup",
            "password": "Backup-Pass-1",
        },
    ).json()["id"]
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "seeded"}
    ).json()["created"][0]["id"]
    assert wait_for_run(auth_client, run_id, timeout=120)["status"] == "success"


def test_missing_database_fails_cleanly(auth_client, server, real_tools):
    instance_id = auth_client.post(
        "/api/instances",
        json={
            "name": f"{server.kind}-missing",
            "host": server.host,
            "port": server.port,
            "username": "root",
            "password": ROOT_PASSWORD,
        },
    ).json()["id"]
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups",
        json={"scope": "single", "database": "does_not_exist"},
    ).json()["created"][0]["id"]
    run = wait_for_run(auth_client, run_id, timeout=120)
    assert (run["status"], run["error_code"]) == ("failed", "database_not_found")
    assert ROOT_PASSWORD not in (run["error_message"] or "")
    assert not [p for p in BACKUP_ROOT.rglob("*") if p.is_file()]
