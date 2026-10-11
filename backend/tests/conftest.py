import os
import tempfile
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
