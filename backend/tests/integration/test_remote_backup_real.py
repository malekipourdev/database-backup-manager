"""A database on another server, backed up by that server's agent (real TLS, real dump
tools, real MySQL/MariaDB), then restored and compared."""

import gzip

import pytest

from tests.conftest import BACKUP_ROOT, wait_for_run
from tests.integration.conftest import REAL_MARIADB_DUMP, REAL_MYSQLDUMP
from tests.integration.test_backup_restore_real import SEED, object_counts, restore, scalar

pytestmark = pytest.mark.integration


def test_backup_through_another_servers_agent(auth_client, server, real_tools, remote_agents):
    server.execute(*SEED)
    setup = auth_client.post(
        "/api/servers", json={"name": f"edge-{server.kind}", "host": "127.0.0.1", "port": 1}
    ).json()
    port = remote_agents(
        setup["token"], mysqldump_path=REAL_MYSQLDUMP, mariadb_dump_path=REAL_MARIADB_DUMP
    )
    server_id = setup["server"]["id"]
    auth_client.patch(f"/api/servers/{server_id}", json={"port": port})
    assert auth_client.post(f"/api/servers/{server_id}/connect").status_code == 200

    instance = auth_client.post(
        "/api/instances",
        json={
            "name": f"remote-{server.kind}",
            "host": server.host,
            "port": server.port,
            "username": "mbp_backup",
            "password": "Backup-Pass-1",
            "server_id": server_id,
        },
    ).json()
    test = auth_client.post(f"/api/instances/{instance['id']}/test-connection").json()
    assert test["ok"] is True and test["server_type"] == server.kind
    listing = auth_client.get(f"/api/instances/{instance['id']}/databases").json()
    assert "seeded" in [d["name"] for d in listing["databases"]]

    run_id = auth_client.post(
        f"/api/instances/{instance['id']}/backups",
        json={"scope": "single", "database": "seeded"},
    ).json()["created"][0]["id"]
    run = wait_for_run(auth_client, run_id, timeout=120)
    assert run["status"] == "success", run
    dump = gzip.decompress(next(BACKUP_ROOT.rglob(run["file_name"])).read_bytes())
    assert b"-- Dump completed" in dump[-200:]
    assert b"Backup-Pass-1" not in dump

    restore(server, dump)
    assert (
        scalar(server, "CHECKSUM TABLE restored.items")[1]
        == scalar(server, "CHECKSUM TABLE seeded.items")[1]
    )
    assert object_counts(server, "restored") == (1, 1, 1, 1)
