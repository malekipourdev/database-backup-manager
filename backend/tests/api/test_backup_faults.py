"""US2 / SC-003: every failure ends 'failed' with a specific code and leaves no files."""

import errno

import pytest

from mbp.backups import pipeline
from mbp.config import get_settings
from mbp.models import DbInstance
from mbp.services import mysql_probe
from tests.conftest import BACKUP_ROOT, INSTANCE_PAYLOAD, create_instance, wait_for_run


def run_single(client, database, instance_id=None):
    instance_id = instance_id or create_instance(client)
    body = client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": database}
    ).json()
    return wait_for_run(client, body["created"][0]["id"])


def assert_failed_cleanly(run, code):
    assert run["status"] == "failed", run
    assert run["error_code"] == code, run
    assert run["error_message"]
    assert INSTANCE_PAYLOAD["password"] not in run["error_message"]
    assert run["file_name"] is None and run["checksum_sha256"] is None
    assert run["file_available"] is False
    leftovers = [p for p in BACKUP_ROOT.rglob("*") if p.is_file()]
    assert leftovers == [], leftovers


@pytest.mark.parametrize(
    ("database", "code"),
    [
        ("crash_db", "connection_lost"),
        ("denied_db", "missing_privileges"),
        ("missing_db", "database_not_found"),
        ("nomarker_db", "verification_failed"),
        ("pwecho_db", "dump_failed"),
    ],
)
def test_dump_failures(auth_client, probe_ok, database, code):
    assert_failed_cleanly(run_single(auth_client, database), code)


def test_preflight_failure_uses_probe_code(auth_client, monkeypatch):
    def unreachable(params, timeout=None):
        return mysql_probe.ProbeResult(
            ok=False, tested_at=mysql_probe.utcnow(), error_code="timeout", error_detail=None
        )

    monkeypatch.setattr(mysql_probe, "test_connection", unreachable)
    run = run_single(auth_client, "ok_db")
    assert run["status"] == "failed"
    assert run["error_code"] == "timeout"


def test_disk_full(auth_client, probe_ok, monkeypatch):
    original = pipeline.HashingWriter.write

    def write(self, data):
        if self.size > 10_000:
            raise OSError(errno.ENOSPC, "No space left on device")
        return original(self, data)

    monkeypatch.setattr(pipeline.HashingWriter, "write", write)
    assert_failed_cleanly(run_single(auth_client, "big_5_db"), "disk_full")


def test_corruption_before_verification(auth_client, app, probe_ok):
    def flip_byte(path):
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))

    app.state.backup_runner.before_verify = flip_byte
    try:
        assert_failed_cleanly(run_single(auth_client, "ok_db"), "verification_failed")
    finally:
        app.state.backup_runner.before_verify = None


def test_tool_missing(auth_client, probe_ok, monkeypatch):
    monkeypatch.setattr(get_settings(), "mysqldump_path", "/nonexistent/mysqldump")
    assert_failed_cleanly(run_single(auth_client, "ok_db"), "tool_missing")


def test_instance_deleted_before_start(auth_client, probe_ok, db, monkeypatch):
    instance_id = create_instance(auth_client)
    runner = auth_client.app.state.backup_runner
    original = runner.enqueue
    monkeypatch.setattr(runner, "enqueue", lambda run_id: None)  # keep it queued
    body = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_db"}
    ).json()
    db.delete(db.get(DbInstance, instance_id))
    db.commit()
    original(body["created"][0]["id"])
    run = wait_for_run(auth_client, body["created"][0]["id"])
    assert run["error_code"] == "instance_deleted"
    assert run["instance_id"] is None
    assert run["instance_name"] == "prod"
