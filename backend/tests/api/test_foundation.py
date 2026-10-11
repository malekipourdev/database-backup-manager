from datetime import timedelta

import pytest
from alembic import command
from fastapi.testclient import TestClient

from mbp.config import get_settings
from mbp.db import utcnow
from mbp.models import AuthSession
from mbp.repositories.session_repository import SessionRepository
from mbp.security import crypto
from mbp.security.sessions import COOKIE_NAME
from tests.conftest import alembic_config


def test_health_without_session(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_route_without_cookie(client):
    response = client.get("/api/instances")
    assert response.status_code == 401
    assert response.json() == {"code": "not_authenticated"}


def test_protected_route_with_unknown_token(client):
    client.cookies.set(COOKIE_NAME, "forged")
    assert client.get("/api/instances").status_code == 401


def test_expired_session_rejected(client, admin, db):
    token = SessionRepository(db).create(admin.id)
    session = db.query(AuthSession).one()
    session.last_activity_at = utcnow() - timedelta(minutes=31)
    db.commit()
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/instances").status_code == 401


def test_active_session_slides(client, admin, db):
    token = SessionRepository(db).create(admin.id)
    session = db.query(AuthSession).one()
    session.last_activity_at = utcnow() - timedelta(minutes=29)
    db.commit()
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/instances").status_code == 200
    db.expire_all()
    assert utcnow() - db.query(AuthSession).one().last_activity_at < timedelta(minutes=1)


def test_post_without_csrf_header_rejected(app, auth_client):
    cookie = auth_client.cookies.get(COOKIE_NAME)
    with TestClient(app) as plain:
        plain.cookies.set(COOKIE_NAME, cookie)
        response = plain.post("/api/instances", json={})
    assert response.status_code == 403
    assert response.json() == {"code": "csrf_failed"}


def test_invalid_encryption_key_fails_startup(monkeypatch):
    monkeypatch.setenv("MBP_ENCRYPTION_KEY", "not-a-valid-key")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="MBP_ENCRYPTION_KEY"):
            crypto.validate_key()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_missing_encryption_key_fails_startup(monkeypatch):
    monkeypatch.delenv("MBP_ENCRYPTION_KEY")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="MBP_ENCRYPTION_KEY"):
            crypto.validate_key()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_migrations_match_models():
    # Fails if the hand-written migration drifts from the ORM models.
    command.check(alembic_config())
