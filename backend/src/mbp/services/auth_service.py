import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.config import Settings
from mbp.db import utcnow
from mbp.logging import register_secret
from mbp.models import AdminAccount, AuthSession, LoginAttempt
from mbp.repositories.admin_repository import AdminRepository
from mbp.repositories.login_attempt_repository import LoginAttemptRepository
from mbp.repositories.session_repository import SessionRepository
from mbp.security.passwords import dummy_verify, hash_password, needs_rehash, verify_password

logger = logging.getLogger(__name__)

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)
USERNAME_MAX = 64


class BootstrapError(RuntimeError):
    pass


def bootstrap_admin(db: Session, settings: Settings) -> None:
    """Create the initial admin from settings when no admin exists yet."""
    if settings.admin_password is not None:
        register_secret(settings.admin_password.get_secret_value())
    admins = AdminRepository(db)
    if admins.count() > 0:
        return
    username = (settings.admin_username or "").strip()
    password = settings.admin_password.get_secret_value() if settings.admin_password else ""
    if not username or not password:
        raise BootstrapError(
            "No admin account exists: set MBP_ADMIN_USERNAME and MBP_ADMIN_PASSWORD"
        )
    if len(username) > USERNAME_MAX:
        raise BootstrapError("MBP_ADMIN_USERNAME must be at most 64 characters")
    admins.create(username, hash_password(password))
    db.commit()
    logger.info("Created initial admin account %r", username.lower())


class AuthService:
    def __init__(self, db: Session, settings: Settings, clock: Callable[[], datetime] = utcnow):
        self.db = db
        self.settings = settings
        self.clock = clock
        self.admins = AdminRepository(db)
        self.attempts = LoginAttemptRepository(db)
        self.sessions = SessionRepository(db)

    def login(self, username: str, password: str) -> tuple[AdminAccount, str]:
        """Verify credentials and return (admin, plain session token).

        Every failure - unknown user, wrong password, or locked out - raises the same
        `invalid_credentials` error so responses reveal nothing about the account.
        """
        key = username.strip().lower()[:USERNAME_MAX]
        now = self.clock()
        attempt = self.attempts.get(key)

        if attempt is not None and attempt.locked_until is not None and now < attempt.locked_until:
            dummy_verify()
            raise ApiError(401, "invalid_credentials")

        admin = self.admins.get_by_username(key)
        if admin is None:
            dummy_verify()
            verified = False
        else:
            verified = verify_password(admin.password_hash, password)

        if not verified or admin is None:
            self._record_failure(key, attempt, now)
            self.db.commit()
            raise ApiError(401, "invalid_credentials")

        self.attempts.delete(key)
        if needs_rehash(admin.password_hash):
            self.admins.update_password_hash(admin, hash_password(password))
        self.admins.touch_last_login(admin)
        self.sessions.purge_expired(self.settings.session_idle_minutes)
        token = self.sessions.create(admin.id)
        self.db.commit()
        return admin, token

    def logout(self, session: AuthSession) -> None:
        self.sessions.delete(session)
        self.db.commit()

    def _record_failure(self, key: str, attempt: LoginAttempt | None, now: datetime) -> None:
        window_expired = attempt is not None and now - attempt.window_started_at >= FAILURE_WINDOW
        lock_expired = (
            attempt is not None and attempt.locked_until is not None and now >= attempt.locked_until
        )
        if attempt is None:
            attempt = LoginAttempt(username=key, failure_count=0, window_started_at=now)
            self.db.add(attempt)
        if window_expired or lock_expired:
            attempt.failure_count = 0
            attempt.window_started_at = now
            attempt.locked_until = None
        attempt.failure_count += 1
        if attempt.failure_count >= MAX_FAILURES:
            attempt.locked_until = now + LOCKOUT
            logger.warning("Login locked for username %r after repeated failures", key)
        self.db.flush()
