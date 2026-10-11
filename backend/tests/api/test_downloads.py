"""US4: streamed downloads and deletion of backups."""

import hashlib
from urllib.parse import quote

from fastapi.testclient import TestClient

from mbp.models import BackupRun
from tests.conftest import BACKUP_ROOT, create_instance, wait_for_run


def backup(client, name="prod", database="ok_shop"):
    instance_id = create_instance(client, name=name)
    run_id = client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": database}
    ).json()["created"][0]["id"]
    return wait_for_run(client, run_id)


def test_download_matches_checksum_and_name(auth_client, probe_ok):
    run = backup(auth_client, name="سرور", database="ok_فروشگاه")
    assert run["status"] == "success"
    response = auth_client.get(f"/api/backups/runs/{run['id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert hashlib.sha256(response.content).hexdigest() == run["checksum_sha256"]
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert f"filename*=utf-8''{quote(run['file_name'])}" in disposition


def test_range_request(auth_client, probe_ok):
    run = backup(auth_client)
    response = auth_client.get(
        f"/api/backups/runs/{run['id']}/download", headers={"Range": "bytes=0-9"}
    )
    assert response.status_code == 206
    assert len(response.content) == 10


def test_download_requires_session(app, auth_client, probe_ok):
    run = backup(auth_client)
    with TestClient(app) as anonymous:
        response = anonymous.get(f"/api/backups/runs/{run['id']}/download")
    assert response.status_code == 401


def test_failed_run_has_no_download(auth_client, probe_ok):
    run = backup(auth_client, database="denied_db")
    response = auth_client.get(f"/api/backups/runs/{run['id']}/download")
    assert response.status_code == 409
    assert response.json()["code"] == "file_unavailable"


def test_file_missing_on_disk(auth_client, probe_ok):
    run = backup(auth_client)
    next(BACKUP_ROOT.rglob("*.sql.gz")).unlink()
    assert auth_client.get(f"/api/backups/runs/{run['id']}").json()["file_available"] is False
    assert auth_client.get(f"/api/backups/runs/{run['id']}/download").status_code == 409


def test_tampered_path_never_served(auth_client, probe_ok, db):
    run = backup(auth_client)
    row = db.get(BackupRun, run["id"])
    row.file_path = "../../../../etc/passwd"
    db.commit()
    response = auth_client.get(f"/api/backups/runs/{run['id']}/download")
    assert response.status_code == 409
    assert "root:" not in response.text


def test_delete_success_removes_file_and_row(auth_client, probe_ok):
    run = backup(auth_client)
    assert any(BACKUP_ROOT.rglob("*.sql.gz"))
    assert auth_client.delete(f"/api/backups/runs/{run['id']}").status_code == 204
    assert not any(BACKUP_ROOT.rglob("*.sql.gz"))
    response = auth_client.get(f"/api/backups/runs/{run['id']}")
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_delete_failed_and_unknown(auth_client, probe_ok):
    run = backup(auth_client, database="denied_db")
    assert auth_client.delete(f"/api/backups/runs/{run['id']}").status_code == 204
    assert auth_client.delete("/api/backups/runs/9999").status_code == 404


def test_cannot_delete_active_run(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "slow_1_db"}
    ).json()["created"][0]["id"]
    response = auth_client.delete(f"/api/backups/runs/{run_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "run_active"
    wait_for_run(auth_client, run_id)
