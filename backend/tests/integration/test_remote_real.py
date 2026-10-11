"""Real backup -> upload to a real S3-compatible server -> retention -> download from the
remote copy -> restore. Covers both MySQL 8.4 and MariaDB 11.8 (`server` is parametrized).

The S3 server is RustFS, a MinIO-compatible server (MinIO no longer publishes images).
Override it with MBP_TEST_S3_IMAGE; the image must accept RUSTFS_ACCESS_KEY/RUSTFS_SECRET_KEY.
"""

import gzip
import os
import time

import boto3
import pytest
from testcontainers.core.container import DockerContainer

from tests.conftest import BACKUP_ROOT, wait_for_remote, wait_for_run
from tests.integration.test_backup_restore_real import SEED, restore, scalar

pytestmark = pytest.mark.integration

S3_IMAGE = os.environ.get(
    "MBP_TEST_S3_IMAGE",
    "rustfs/rustfs@sha256:1803faef57627e2d9c2e7d89d655d712ddded5389040054987163043fecb6a3c",
)
S3_USER = "mbp-s3-user"
S3_PASSWORD = "S3-Secret-Pass-123"
BUCKET = "backups"


@pytest.fixture(scope="session")
def s3_server_real():
    container = (
        DockerContainer(S3_IMAGE)
        .with_env("RUSTFS_ACCESS_KEY", S3_USER)
        .with_env("RUSTFS_SECRET_KEY", S3_PASSWORD)
        .with_command("/data")
        .with_exposed_ports(9000)
    )
    with container:
        endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9000)}"
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name="us-east-1",
            aws_access_key_id=S3_USER,
            aws_secret_access_key=S3_PASSWORD,
        )
        deadline = time.monotonic() + 60
        while True:  # the server needs a few seconds to start
            try:
                client.create_bucket(Bucket=BUCKET)
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
        client.endpoint = endpoint
        yield client


def test_upload_retention_and_restore_from_remote(auth_client, server, real_tools, s3_server_real):
    s3 = s3_server_real
    server.execute(*SEED)
    settings = auth_client.put(
        "/api/remote-storage",
        json={
            "enabled": True,
            "endpoint_url": s3.endpoint,
            "region": "us-east-1",
            "bucket": BUCKET,
            "prefix": server.kind,
            "access_key_id": S3_USER,
            "secret_access_key": S3_PASSWORD,
            "force_path_style": True,
        },
    )
    assert settings.status_code == 200, settings.text
    test = auth_client.post(
        "/api/remote-storage/test",
        json={
            "endpoint_url": s3.endpoint,
            "bucket": BUCKET,
            "access_key_id": S3_USER,
            "secret_access_key": S3_PASSWORD,
        },
    ).json()
    assert test["ok"] is True, test

    instance_id = auth_client.post(
        "/api/instances",
        json={
            "name": f"{server.kind}-remote",
            "host": server.host,
            "port": server.port,
            "username": "mbp_backup",
            "password": "Backup-Pass-1",
        },
    ).json()["id"]
    # Keep only the newest local file; the remote copies are kept.
    auth_client.put("/api/retention", json={"local_keep_last": 1})

    def backup():
        run_id = auth_client.post(
            f"/api/instances/{instance_id}/backups", json={"scope": "single", "database": "seeded"}
        ).json()["created"][0]["id"]
        assert wait_for_run(auth_client, run_id, timeout=120)["status"] == "success"
        return wait_for_remote(auth_client, run_id, timeout=60)

    first = backup()
    time.sleep(1.1)  # distinct file names (the pattern has one-second resolution)
    second = backup()
    assert first["remote_status"] == second["remote_status"] == "success"

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        first = auth_client.get(f"/api/backups/runs/{first['id']}").json()
        if first["file_deleted_at"]:
            break
        time.sleep(0.1)
    assert first["file_deleted_reason"] == "retention"
    assert not list(BACKUP_ROOT.rglob(first["file_name"]))

    # The local file is gone, so the download streams the remote copy.
    response = auth_client.get(f"/api/backups/runs/{first['id']}/download")
    assert response.status_code == 200
    dump = gzip.decompress(response.content)
    assert b"-- Dump completed" in dump[-200:]
    restore(server, dump)
    assert (
        scalar(server, "CHECKSUM TABLE restored.items")[1]
        == scalar(server, "CHECKSUM TABLE seeded.items")[1]
    )

    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=server.kind)["Contents"]]
    assert len(keys) == 2
    assert S3_PASSWORD not in str(auth_client.get("/api/remote-storage").json())
