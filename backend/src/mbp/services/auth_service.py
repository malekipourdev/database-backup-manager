import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.config import Settings
from mbp.db import utcnow
from mbp.logging import register_secret
from mbp.models import AdminAccount, AuthSession, LoginAttempt
from mbp.repositories.admin_repository import AdminRepository
from mbp.repositories.login_attempt_repository import LoginAttemptRepository
from mbp.repositories.session_repository import SessionRepository
from mbp.security import crypto, totp
from mbp.security.passwords import dummy_verify, hash_password, needs_rehash, verify_password

logger = logging.getLogger(__name__)

MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)
USERNAME_MAX = 64


CHALLENGE_TTL_SECONDS = 300
CHALLENGE_PURPOSE = "login-2fa"


class BootstrapError(RuntimeError):
    pass


@dataclass
class LoginResult:
    admin: AdminAccount
    # Session token when signed in; `challenge` instead when a second factor is needed.
    token: str | None = None
    challenge: str | None = None


def _password_tag(admin: AdminAccount) -> str:
    # Ties a challenge to the current password: changing it invalidates open challenges.
    return hashlib.sha256(admin.password_hash.encode("utf-8")).hexdigest()[:16]


def make_challenge(admin: AdminAccount) -> str:
    """An encrypted, 5-minute token proving the password step passed for this admin."""
    payload = {"p": CHALLENGE_PURPOSE, "a": admin.id, "t": _password_tag(admin)}
    return crypto.encrypt(json.dumps(payload))


def read_challenge(challenge: str, admins: AdminRepository) -> int:
    try:
        payload = json.loads(crypto.decrypt(challenge, ttl=CHALLENGE_TTL_SECONDS))
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ApiError(401, "challenge_expired") from exc
    if not isinstance(payload, dict) or payload.get("p") != CHALLENGE_PURPOSE:
        raise ApiError(401, "challenge_expired")
    admin = admins.get(int(payload.get("a", 0)))
    if admin is None or not hmac.compare_digest(str(payload.get("t")), _password_tag(admin)):
        raise ApiError(401, "challenge_expired")
    return admin.id


def check_second_factor(admin: AdminAccount, code: str, now: float) -> bool:
    """Accept a fresh TOTP code or an unused recovery code (which is then used up)."""
    if not admin.totp_secret_encrypted:
        return False
    secret = crypto.decrypt(admin.totp_secret_encrypted)
    step = totp.verify(secret, code, admin.totp_last_step, now)
    if step is not None:
        admin.totp_last_step = step
        return True
    remaining = totp.use_recovery_code(admin.totp_recovery_hashes, code)
    if remaining is not None:
        admin.totp_recovery_hashes = remaining
        logger.warning("Admin %r signed in with a recovery code", admin.username)
        return True
    return False


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

    def login(self, username: str, password: str) -> LoginResult:
        """Verify credentials; sign in, or ask for the second factor if 2FA is on.

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

        if needs_rehash(admin.password_hash):
            self.admins.update_password_hash(admin, hash_password(password))
        if admin.totp_enabled:
            # The password was right; the failure count is reset only after the code.
            self.db.commit()
            return LoginResult(admin=admin, challenge=make_challenge(admin))
        self.attempts.delete(key)
        return LoginResult(admin=admin, token=self._start_session(admin))

    def _start_session(self, admin: AdminAccount) -> str:
        self.admins.touch_last_login(admin)
        self.sessions.purge_expired(self.settings.session_idle_minutes)
        token = self.sessions.create(admin.id)
        self.db.commit()
        return token

    def login_second_factor(self, challenge: str, code: str) -> LoginResult:
        """Finish a 2FA sign-in with a TOTP code or a one-time recovery code."""
        admin = self.admins.get(read_challenge(challenge, self.admins))
        if admin is None or not admin.totp_enabled:
            raise ApiError(401, "challenge_expired")
        key = admin.username
        now = self.clock()
        attempt = self.attempts.get(key)
        if attempt is not None and attempt.locked_until is not None and now < attempt.locked_until:
            raise ApiError(401, "invalid_code")
        if not check_second_factor(admin, code, now.timestamp()):
            self._record_failure(key, attempt, now)
            self.db.commit()
            raise ApiError(401, "invalid_code")
        self.attempts.delete(key)
        return LoginResult(admin=admin, token=self._start_session(admin))

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
