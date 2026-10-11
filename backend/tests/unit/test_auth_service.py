from datetime import timedelta

import pytest
from pydantic import SecretStr

from mbp.api.errors import ApiError
from mbp.config import Settings, get_settings
from mbp.db import utcnow
from mbp.models import AdminAccount, LoginAttempt
from mbp.services.auth_service import AuthService, BootstrapError, bootstrap_admin
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


class Clock:
    def __init__(self) -> None:
        self.now = utcnow()

    def __call__(self):
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(db, admin, clock):
    return AuthService(db, get_settings(), clock=clock)


def fail(service, username=ADMIN_USERNAME, password="wrong"):
    with pytest.raises(ApiError) as info:
        service.login(username, password)
    assert info.value.status == 401
    assert info.value.code == "invalid_credentials"


def test_successful_login_returns_token(service):
    result = service.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    admin, token = result.admin, result.token
    assert admin.username == ADMIN_USERNAME
    assert len(token) >= 40


def test_username_is_case_insensitive(service):
    admin = service.login("ADMIN", ADMIN_PASSWORD).admin
    assert admin.username == ADMIN_USERNAME


def test_four_failures_then_success_resets(service, db):
    for _ in range(4):
        fail(service)
    service.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    assert db.get(LoginAttempt, ADMIN_USERNAME) is None


def test_five_failures_lock_for_fifteen_minutes(service, db, clock):
    for _ in range(5):
        fail(service)
    attempt = db.get(LoginAttempt, ADMIN_USERNAME)
    assert attempt.locked_until == clock.now + timedelta(minutes=15)

    # Correct password is refused while locked.
    fail(service, password=ADMIN_PASSWORD)
    clock.advance(minutes=14, seconds=59)
    fail(service, password=ADMIN_PASSWORD)

    clock.advance(seconds=2)
    admin = service.login(ADMIN_USERNAME, ADMIN_PASSWORD).admin
    assert admin.username == ADMIN_USERNAME


def test_failure_after_window_restarts_count(service, db, clock):
    for _ in range(4):
        fail(service)
    clock.advance(minutes=16)
    fail(service)
    assert db.get(LoginAttempt, ADMIN_USERNAME).failure_count == 1
    assert db.get(LoginAttempt, ADMIN_USERNAME).locked_until is None


def test_unknown_usernames_are_throttled_too(service, db):
    for _ in range(5):
        fail(service, username="ghost")
    assert db.get(LoginAttempt, "ghost").locked_until is not None


def _settings(**overrides) -> Settings:
    base = {"encryption_key": get_settings().encryption_key}
    return Settings(**base, **overrides)


def test_bootstrap_creates_admin_when_table_empty(db):
    bootstrap_admin(db, _settings(admin_username="Root", admin_password=SecretStr("pw-12345")))
    admin = db.query(AdminAccount).one()
    assert admin.username == "root"
    assert admin.password_hash.startswith("$argon2id$")


def test_bootstrap_ignored_when_admin_exists(db, admin):
    bootstrap_admin(db, _settings(admin_username="other", admin_password=SecretStr("pw-12345")))
    assert [a.username for a in db.query(AdminAccount)] == [ADMIN_USERNAME]


def test_bootstrap_fails_without_env_when_empty(db):
    with pytest.raises(BootstrapError, match="MBP_ADMIN_USERNAME"):
        bootstrap_admin(db, _settings(admin_username=None, admin_password=None))
