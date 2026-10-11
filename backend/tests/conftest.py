import os
import shutil
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet

# Configure the app before anything imports mbp.*.
_TMP = Path(tempfile.mkdtemp(prefix="mbp-test-"))
TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Adm1n-pass"
os.environ["MBP_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
os.environ["MBP_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["MBP_ADMIN_USERNAME"] = ADMIN_USERNAME
os.environ["MBP_ADMIN_PASSWORD"] = ADMIN_PASSWORD
os.environ["MBP_COOKIE_SECURE"] = "false"
BACKUP_ROOT = _TMP / "backups"
FAKE_DUMP = Path(__file__).resolve().parent / "fakes" / "fake_dump.py"
os.environ["MBP_BACKUP_ROOT"] = str(BACKUP_ROOT)
os.environ["MBP_MYSQLDUMP_PATH"] = str(FAKE_DUMP)
os.environ["MBP_MARIADB_DUMP_PATH"] = str(FAKE_DUMP)
os.environ["MBP_BACKUP_PROGRESS_INTERVAL_SECONDS"] = "0.2"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from mbp.db import Base, get_engine, get_sessionmaker  # noqa: E402
from mbp.models import AdminAccount  # noqa: E402
from mbp.repositories.admin_repository import AdminRepository  # noqa: E402
from mbp.repositories.session_repository import SessionRepository  # noqa: E402
from mbp.security.passwords import hash_password  # noqa: E402
from mbp.security.sessions import COOKIE_NAME  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    command.upgrade(alembic_config(), "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    with get_engine().begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))


@pytest.fixture
def db():
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app():
    from mbp.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    """Unauthenticated client; sends the CSRF header by default."""
    with TestClient(app, headers={"X-Requested-With": "mbp"}) as test_client:
        yield test_client


@pytest.fixture
def admin(db) -> AdminAccount:
    repo = AdminRepository(db)
    existing = repo.get_by_username(ADMIN_USERNAME)
    if existing is not None:
        return existing
    created = repo.create(ADMIN_USERNAME, hash_password(ADMIN_PASSWORD))
    db.commit()
    return created


@pytest.fixture
def auth_client(client, admin, db):
    """Client with a valid session created directly in the database."""
    token = SessionRepository(db).create(admin.id)
    db.commit()
    client.cookies.set(COOKIE_NAME, token)
    return client


# --- Backups ---


@pytest.fixture(autouse=True)
def backup_root():
    """Fresh, empty backup storage area for every test."""
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    yield BACKUP_ROOT
    shutil.rmtree(BACKUP_ROOT, ignore_errors=True)


@pytest.fixture
def probe_ok(monkeypatch):
    """Pre-flight connection test succeeds and reports a MySQL 8.4 server."""
    from mbp.services import mysql_probe

    def fake(params, timeout=None):
        return mysql_probe.ProbeResult(
            ok=True, tested_at=mysql_probe.utcnow(), server_type="mysql", server_version="8.4.3"
        )

    monkeypatch.setattr(mysql_probe, "test_connection", fake)


INSTANCE_PAYLOAD = {
    "name": "prod",
    "host": "db.internal",
    "port": 3306,
    "username": "backup",
    "password": "Inst-Secret-77",
}


def create_instance(client, name="prod", select=()):
    """Create an instance via the API and store a database selection directly."""
    from mbp.models import DbSelection

    response = client.post("/api/instances", json={**INSTANCE_PAYLOAD, "name": name})
    assert response.status_code == 201, response.text
    instance_id = response.json()["id"]
    if select:
        with get_sessionmaker()() as session:
            session.add_all(DbSelection(instance_id=instance_id, database_name=n) for n in select)
            session.commit()
    return instance_id


def wait_for_run(client, run_id, timeout=15.0):
    """Poll a run until it is finished; returns its JSON."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/backups/runs/{run_id}").json()
        if body["status"] in ("success", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


# --- Remote storage (S3 API served by moto on localhost) ---

S3_BUCKET = "mbp-test"
S3_ACCESS_KEY = "AKIA-TEST-ACCESS"
S3_SECRET_KEY = "S3-Secret-Key-123"


@pytest.fixture(scope="session")
def s3_server():
    import socket

    from moto.server import ThreadedMotoServer

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def s3(s3_server):
    """An empty bucket on the local S3 server; returns a boto3 client for assertions."""
    import boto3
    import httpx

    httpx.post(f"{s3_server}/moto-api/reset")
    client = boto3.client(
        "s3",
        endpoint_url=s3_server,
        region_name="us-east-1",
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )
    client.create_bucket(Bucket=S3_BUCKET)
    client.endpoint = s3_server
    return client


def remote_payload(endpoint, **overrides):
    payload = {
        "enabled": True,
        "endpoint_url": endpoint,
        "region": "us-east-1",
        "bucket": S3_BUCKET,
        "prefix": "panel",
        "access_key_id": S3_ACCESS_KEY,
        "secret_access_key": S3_SECRET_KEY,
        "force_path_style": True,
    }
    payload.update(overrides)
    return payload


def wait_for_remote(client, run_id, timeout=15.0):
    """Poll a run until its upload has finished (or never started)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/backups/runs/{run_id}").json()
        if body["status"] in ("success", "failed") and body["remote_status"] != "uploading":
            return body
        time.sleep(0.05)
    raise AssertionError(f"upload of run {run_id} did not finish in {timeout}s")
