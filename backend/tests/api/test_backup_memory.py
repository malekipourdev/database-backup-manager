"""SC-004: memory stays bounded when writing and downloading a large backup."""

import resource

import anyio

from mbp.repositories.session_repository import SessionRepository
from mbp.security.sessions import COOKIE_NAME
from tests.conftest import create_instance, wait_for_run

LIMIT_KB = 300 * 1024  # ru_maxrss is in KiB on Linux


def max_rss_kb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def test_large_backup_and_download_use_bounded_memory(auth_client, probe_ok, app, admin, db):
    before = max_rss_kb()
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups",
        json={"scope": "single", "database": "big_1024_db"},
    ).json()["created"][0]["id"]
    run = wait_for_run(auth_client, run_id, timeout=300)
    assert run["status"] == "success", run
    assert run["bytes_processed"] >= 1024 * 1024 * 1024
    assert max_rss_kb() - before < LIMIT_KB

    # Drive the ASGI app directly and discard chunks; the TestClient would buffer the body.
    token = SessionRepository(db).create(admin.id)
    db.commit()
    received = 0
    status = None

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        nonlocal received, status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            received += len(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/backups/runs/{run_id}/download",
        "raw_path": f"/api/backups/runs/{run_id}/download".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver"), (b"cookie", f"{COOKIE_NAME}={token}".encode())],
        "client": ("127.0.0.1", 1),
        "server": ("testserver", 80),
        "state": {},
    }
    before_download = max_rss_kb()
    anyio.run(app, scope, receive, send)
    assert status == 200
    assert received == run["file_size"]
    assert max_rss_kb() - before_download < LIMIT_KB
