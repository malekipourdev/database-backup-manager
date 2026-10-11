"""US1: on-demand backups (fake dump tool + successful pre-flight probe)."""

import gzip
import hashlib
import time

from tests.conftest import BACKUP_ROOT, create_instance, wait_for_run


def start(client, instance_id, **body):
    return client.post(f"/api/instances/{instance_id}/backups", json=body)


def test_back_up_all_marked_databases(auth_client, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop", "ok_blog"))
    response = start(auth_client, instance_id, scope="all")
    assert response.status_code == 202
    body = response.json()
    assert body["skipped"] == []
    assert sorted(r["database_name"] for r in body["created"]) == ["ok_blog", "ok_shop"]
    assert all(r["status"] == "queued" and r["trigger"] == "all" for r in body["created"])

    for created in body["created"]:
        run = wait_for_run(auth_client, created["id"])
        assert run["status"] == "success", run
        path = BACKUP_ROOT / "prod" / run["file_name"]
        assert path.is_file()
        assert run["file_name"].startswith(f"{run['database_name']}_")
        assert run["file_name"].endswith(".sql.gz")
        assert run["file_size"] == path.stat().st_size
        assert run["checksum_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert gzip.decompress(path.read_bytes()).rstrip().endswith(b"12:00:00")
        assert run["compression"] == "gzip"
        assert run["server_type"] == "mysql"
        assert run["started_at"] and run["finished_at"]
        assert run["duration_ms"] is not None
        assert run["bytes_processed"] > 200_000
        assert run["file_available"] is True


def test_single_database_even_if_not_marked(auth_client, probe_ok):
    instance_id = create_instance(auth_client, select=("ok_shop",))
    body = start(auth_client, instance_id, scope="single", database="ok_other").json()
    assert len(body["created"]) == 1
    run = wait_for_run(auth_client, body["created"][0]["id"])
    assert run["status"] == "success"
    assert run["trigger"] == "single"
    assert run["database_name"] == "ok_other"
    files = [p for p in BACKUP_ROOT.rglob("*") if p.is_file()]
    assert len(files) == 1


def test_system_schema_not_selectable(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    response = start(auth_client, instance_id, scope="single", database="information_schema")
    assert response.status_code == 422
    assert response.json()["code"] == "not_selectable"


def test_all_with_nothing_marked(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    response = start(auth_client, instance_id, scope="all")
    assert response.status_code == 422
    assert response.json()["code"] == "no_databases_selected"


def test_unknown_instance_and_bad_body(auth_client, probe_ok):
    assert start(auth_client, 9999, scope="all").status_code == 404
    instance_id = create_instance(auth_client)
    assert start(auth_client, instance_id, scope="single").status_code == 422
    assert start(auth_client, instance_id, scope="other").status_code == 422


def test_start_returns_immediately(auth_client, probe_ok):
    # SC-006: starting never waits for the dump itself.
    instance_id = create_instance(auth_client)
    started = time.monotonic()
    body = start(auth_client, instance_id, scope="single", database="slow_2_db").json()
    assert time.monotonic() - started < 1
    assert body["created"][0]["status"] == "queued"
    assert wait_for_run(auth_client, body["created"][0]["id"])["status"] == "success"


def test_instance_override_compression_none(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    auth_client.put(
        f"/api/instances/{instance_id}/backup-settings",
        json={"storage_dir": None, "name_pattern": None, "compression": "none"},
    )
    run_id = start(auth_client, instance_id, scope="single", database="ok_x").json()["created"][0][
        "id"
    ]
    run = wait_for_run(auth_client, run_id)
    assert run["compression"] == "none"
    assert run["file_name"].endswith(".sql")
