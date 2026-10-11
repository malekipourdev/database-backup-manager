"""Remote (S3-compatible) storage: settings, upload, download fallback, delete, retention."""

import hashlib
import logging
import time
from datetime import datetime, timedelta

import pytest

from tests.conftest import (
    BACKUP_ROOT,
    S3_BUCKET,
    S3_SECRET_KEY,
    create_instance,
    remote_payload,
    wait_for_remote,
    wait_for_run,
)


def configure(client, s3, **overrides):
    response = client.put("/api/remote-storage", json=remote_payload(s3.endpoint, **overrides))
    assert response.status_code == 200, response.text
    return response.json()


def backup(client, instance_id, database="ok_shop"):
    run_id = client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": database}
    ).json()["created"][0]["id"]
    wait_for_run(client, run_id)
    return wait_for_remote(client, run_id)


def objects(s3):
    return [o["Key"] for o in s3.list_objects_v2(Bucket=S3_BUCKET).get("Contents", [])]


def test_settings_never_return_the_secret(auth_client, s3):
    initial = auth_client.get("/api/remote-storage").json()
    assert initial["enabled"] is False
    assert initial["has_secret"] is False

    saved = configure(auth_client, s3)
    assert saved["has_secret"] is True
    assert saved["bucket"] == S3_BUCKET
    assert S3_SECRET_KEY not in str(saved)

    # Saving again without a secret keeps the stored one.
    payload = remote_payload(s3.endpoint, prefix="other")
    del payload["secret_access_key"]
    again = auth_client.put("/api/remote-storage", json=payload).json()
    assert again["has_secret"] is True
    assert again["prefix"] == "other"

    cleared = auth_client.delete("/api/remote-storage/secret").json()
    assert cleared["has_secret"] is False
    assert cleared["enabled"] is False


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"bucket": ""}, "bucket"),
        ({"access_key_id": ""}, "access_key_id"),
        ({"secret_access_key": ""}, "secret_access_key"),
    ],
)
def test_enabled_requires_complete_settings(auth_client, s3, overrides, field):
    response = auth_client.put("/api/remote-storage", json=remote_payload(s3.endpoint, **overrides))
    assert response.status_code == 422
    assert field in response.json()["fields"]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"endpoint_url": "ftp://example.com"}, "endpoint_url"),
        ({"endpoint_url": "http://exa mple.com"}, "endpoint_url"),
        ({"bucket": "bad bucket"}, "bucket"),
        ({"prefix": "a/../b"}, "prefix"),
    ],
)
def test_input_validation(auth_client, s3, overrides, field):
    response = auth_client.put("/api/remote-storage", json=remote_payload(s3.endpoint, **overrides))
    assert response.status_code == 422
    assert field in response.json()["fields"]


def test_connection_test(auth_client, s3):
    ok = auth_client.post("/api/remote-storage/test", json=remote_payload(s3.endpoint)).json()
    assert ok == {"ok": True, "error_code": None, "error_detail": None}
    # The write probe is cleaned up.
    assert objects(s3) == []

    missing = auth_client.post(
        "/api/remote-storage/test", json=remote_payload(s3.endpoint, bucket="nope-bucket")
    ).json()
    assert missing["ok"] is False
    assert missing["error_code"] == "bucket_not_found"

    unreachable = auth_client.post(
        "/api/remote-storage/test", json=remote_payload("http://127.0.0.1:9")
    ).json()
    assert unreachable["ok"] is False
    assert unreachable["error_code"] == "endpoint_unreachable"


def test_connection_test_uses_stored_secret(auth_client, s3):
    payload = remote_payload(s3.endpoint)
    del payload["secret_access_key"]
    response = auth_client.post("/api/remote-storage/test", json=payload)
    assert response.status_code == 422
    configure(auth_client, s3)
    assert auth_client.post("/api/remote-storage/test", json=payload).json()["ok"] is True


def test_backup_is_uploaded(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    assert run["remote_status"] == "success"
    assert run["remote_available"] is True
    assert run["remote_uploaded_at"] is not None

    key = f"panel/prod/{run['file_name']}"
    assert objects(s3) == [key]
    stored = s3.get_object(Bucket=S3_BUCKET, Key=key)
    body = stored["Body"].read()
    assert hashlib.sha256(body).hexdigest() == run["checksum_sha256"]
    assert stored["Metadata"]["sha256"] == run["checksum_sha256"]
    assert len(body) == run["file_size"]


def test_large_backup_uses_multipart_upload(auth_client, s3, probe_ok, monkeypatch):
    from boto3.s3.transfer import TransferConfig

    from mbp.backups import remote

    small = TransferConfig(multipart_threshold=5 * 1024 * 1024, multipart_chunksize=5 * 1024 * 1024)
    monkeypatch.setattr(remote, "_TRANSFER", small)
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    # Random-looking data compresses poorly; use "none" so the file is big enough to split.
    auth_client.put(
        "/api/backup-settings",
        json={
            "storage_dir": "",
            "name_pattern": "{instance}/{database}_{datetime}",
            "compression": "none",
        },
    )
    run = backup(auth_client, instance_id, database="big_12_db")
    assert run["remote_status"] == "success", run
    head = s3.head_object(Bucket=S3_BUCKET, Key=f"panel/prod/{run['file_name']}")
    assert head["ContentLength"] == run["file_size"]
    assert "-" in head["ETag"]  # multipart ETags end in "-<parts>"


def test_upload_disabled_globally_or_per_instance(auth_client, s3, probe_ok):
    configure(auth_client, s3, enabled=False)
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    assert run["remote_status"] is None
    assert objects(s3) == []

    # An instance can opt in while the global default is off ...
    auth_client.put(
        f"/api/instances/{instance_id}/storage-policy", json={"remote_upload": "enabled"}
    )
    run = backup(auth_client, instance_id)
    assert run["remote_status"] == "success"

    # ... or opt out while it is on.
    configure(auth_client, s3, enabled=True)
    policy = auth_client.put(
        f"/api/instances/{instance_id}/storage-policy", json={"remote_upload": "disabled"}
    ).json()
    assert policy["effective_upload"] is False
    run = backup(auth_client, instance_id)
    assert run["remote_status"] is None


def test_upload_failure_is_recorded_and_retryable(auth_client, s3, probe_ok):
    configure(auth_client, s3, bucket="missing-bucket")
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    # The backup itself succeeded; only the upload failed, visibly.
    assert run["status"] == "success"
    assert run["remote_status"] == "failed"
    assert "bucket_not_found" in run["remote_error"]
    assert S3_SECRET_KEY not in run["remote_error"]

    configure(auth_client, s3)
    response = auth_client.post(f"/api/backups/runs/{run['id']}/upload")
    assert response.status_code == 202
    retried = wait_for_remote(auth_client, run["id"])
    assert retried["remote_status"] == "success"
    assert retried["remote_error"] is None
    again = auth_client.post(f"/api/backups/runs/{run['id']}/upload")
    assert again.status_code == 409
    assert again.json()["code"] == "already_uploaded"


def test_retry_upload_requires_configuration(auth_client, probe_ok):
    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_shop"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    response = auth_client.post(f"/api/backups/runs/{run_id}/upload")
    assert response.status_code == 409
    assert response.json()["code"] == "remote_not_configured"


def test_download_falls_back_to_remote_copy(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    next(BACKUP_ROOT.rglob("*.sql.gz")).unlink()

    body = auth_client.get(f"/api/backups/runs/{run['id']}").json()
    assert body["file_available"] is False
    assert body["download_available"] is True
    response = auth_client.get(f"/api/backups/runs/{run['id']}/download")
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == run["checksum_sha256"]
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["content-type"] == "application/gzip"


def age_remote(run_id, days):
    """Pretend the run's remote copy was uploaded `days` ago."""
    from datetime import UTC, datetime, timedelta

    from mbp.db import get_sessionmaker
    from mbp.models import BackupRun

    with get_sessionmaker()() as db:
        run = db.get(BackupRun, run_id)
        run.remote_uploaded_at = datetime.now(UTC) - timedelta(days=days)
        db.commit()


def test_delete_keeps_remote_copy_by_default(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    assert auth_client.delete(f"/api/backups/runs/{run['id']}").status_code == 204
    # The local file is gone, the remote copy and the record stay.
    assert list(BACKUP_ROOT.rglob("*.sql.gz")) == []
    assert len(objects(s3)) == 1
    body = auth_client.get(f"/api/backups/runs/{run['id']}").json()
    assert body["file_deleted_reason"] == "manual"
    assert body["remote_available"] is True
    assert body["download_available"] is True
    assert auth_client.get(f"/api/backups/runs/{run['id']}/download").status_code == 200
    # Nothing left that may be deleted now: the remote copy is protected.
    again = auth_client.delete(f"/api/backups/runs/{run['id']}")
    assert again.status_code == 409 and again.json()["code"] == "nothing_to_delete"


def test_remote_copy_is_protected_for_seven_days(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    assert run["remote_deletable"] is False
    deletable_at = datetime.fromisoformat(run["remote_deletable_at"])
    uploaded_at = datetime.fromisoformat(run["remote_uploaded_at"])
    assert deletable_at - uploaded_at == timedelta(days=7)

    refused = auth_client.delete(f"/api/backups/runs/{run['id']}", params={"remote": "true"})
    assert refused.status_code == 409
    assert refused.json()["code"] == "remote_protected"
    assert datetime.fromisoformat(refused.json()["detail"]) == deletable_at
    # Refused as a whole: nothing was deleted, locally or remotely.
    assert len(objects(s3)) == 1
    assert len(list(BACKUP_ROOT.rglob("*.sql.gz"))) == 1

    age_remote(run["id"], 7)
    assert auth_client.get(f"/api/backups/runs/{run['id']}").json()["remote_deletable"] is True
    ok = auth_client.delete(f"/api/backups/runs/{run['id']}", params={"remote": "true"})
    assert ok.status_code == 204
    assert objects(s3) == []
    assert list(BACKUP_ROOT.rglob("*.sql.gz")) == []
    assert auth_client.get(f"/api/backups/runs/{run['id']}").status_code == 404


def test_delete_remote_copy_after_local_is_gone(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    run = backup(auth_client, instance_id)
    auth_client.delete(f"/api/backups/runs/{run['id']}")
    age_remote(run["id"], 8)
    ok = auth_client.delete(f"/api/backups/runs/{run['id']}", params={"remote": "true"})
    assert ok.status_code == 204
    assert objects(s3) == []
    assert auth_client.get(f"/api/backups/runs/{run['id']}").status_code == 404


def test_remote_retention(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    first = backup(auth_client, instance_id)
    age_remote(first["id"], 10)  # older than the 7-day protection
    auth_client.put("/api/retention", json={"remote_keep_last": 1})
    second = backup(auth_client, instance_id)
    # Retention runs right after the upload; give it a moment.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        first = auth_client.get(f"/api/backups/runs/{first['id']}").json()
        if first["remote_status"] == "deleted":
            break
        time.sleep(0.05)
    assert first["remote_status"] == "deleted"
    assert first["remote_deleted_at"] is not None
    # Local files are kept: only the remote policy is set.
    assert first["file_available"] is True
    assert objects(s3) == [f"panel/prod/{second['file_name']}"]


def test_remote_retention_errors_are_reported(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    first = backup(auth_client, instance_id)
    age_remote(first["id"], 10)
    backup(auth_client, instance_id)
    # Remote storage becomes unusable, then retention tries to delete the older copy.
    configure(auth_client, s3, endpoint_url="http://127.0.0.1:9")
    auth_client.put("/api/retention", json={"remote_keep_last": 1})
    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert [item["run_id"] for item in report["errors"]] == [first["id"]]
    assert report["errors"][0]["error_code"] == "endpoint_unreachable"
    body = auth_client.get(f"/api/backups/runs/{first['id']}").json()
    assert body["remote_status"] == "success"
    assert "endpoint_unreachable" in body["remote_error"]


def test_secret_never_logged(auth_client, s3, probe_ok, caplog):
    caplog.set_level(logging.DEBUG)
    configure(auth_client, s3, bucket="missing-bucket")
    instance_id = create_instance(auth_client)
    backup(auth_client, instance_id)
    auth_client.post("/api/remote-storage/test", json=remote_payload(s3.endpoint, bucket="nope"))
    assert S3_SECRET_KEY not in caplog.text


def test_interrupted_upload_is_failed_on_restart(auth_client, app, probe_ok):
    from mbp.db import get_sessionmaker
    from mbp.models import BackupRun

    instance_id = create_instance(auth_client)
    run_id = auth_client.post(
        f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "ok_shop"}
    ).json()["created"][0]["id"]
    wait_for_run(auth_client, run_id)
    with get_sessionmaker()() as db:
        db.get(BackupRun, run_id).remote_status = "uploading"
        db.commit()
    app.state.backup_runner.recover()
    run = auth_client.get(f"/api/backups/runs/{run_id}").json()
    assert run["remote_status"] == "failed"
    assert "interrupted" in run["remote_error"].lower()


def test_retention_never_deletes_young_remote_copies(auth_client, s3, probe_ok):
    configure(auth_client, s3)
    instance_id = create_instance(auth_client)
    runs = [backup(auth_client, instance_id) for _ in range(3)]
    auth_client.put("/api/retention", json={"remote_keep_last": 1})
    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert report["deleted"] == [] and report["errors"] == []
    assert len(objects(s3)) == 3
    # Once old enough, the policy applies (the newest copy is kept, as always).
    for run in runs:
        age_remote(run["id"], 8)
    report = auth_client.post("/api/retention/apply", json={"dry_run": False}).json()
    assert len([i for i in report["deleted"] if i["target"] == "remote"]) == 2
    assert len(objects(s3)) == 1


def test_remote_age_limit_cannot_be_below_seven_days(auth_client):
    response = auth_client.put("/api/retention", json={"remote_max_age_days": 3})
    assert response.status_code == 422
    assert auth_client.put("/api/retention", json={"remote_max_age_days": 7}).status_code == 200
