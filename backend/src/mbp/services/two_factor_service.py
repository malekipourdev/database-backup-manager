"""Turning two-factor authentication (TOTP) on and off for an admin."""

import logging
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.db import utcnow
from mbp.logging import register_secret
from mbp.models import AdminAccount, AuthSession
from mbp.security import crypto, totp
from mbp.security.passwords import verify_password
from mbp.services.auth_service import check_second_factor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetupInfo:
    secret: str
    otpauth_uri: str
    qr_svg: str


class TwoFactorService:
    def __init__(self, db: Session, admin: AdminAccount) -> None:
        self.db = db
        self.admin = admin

    def _require_password(self, password: str) -> None:
        if not verify_password(self.admin.password_hash, password):
            raise ApiError(403, "wrong_password", fields={"password": "wrong_password"})

    def _require_code(self, code: str) -> None:
        if not check_second_factor(self.admin, code, utcnow().timestamp()):
            raise ApiError(403, "invalid_code", fields={"code": "invalid_code"})

    def _end_other_sessions(self, keep: AuthSession | None) -> None:
        stmt = delete(AuthSession).where(AuthSession.admin_id == self.admin.id)
        if keep is not None:
            stmt = stmt.where(AuthSession.id != keep.id)
        self.db.execute(stmt)

    def status(self) -> tuple[bool, int]:
        return self.admin.totp_enabled, len(self.admin.totp_recovery_hashes or [])

    def start_setup(self, password: str) -> SetupInfo:
        """A new secret to scan; it takes effect only after `enable` confirms a code."""
        self._require_password(password)
        if self.admin.totp_enabled:
            raise ApiError(409, "two_factor_already_enabled")
        secret = totp.new_secret()
        register_secret(secret)
        self.admin.totp_pending_secret_encrypted = crypto.encrypt(secret)
        self.db.commit()
        uri = totp.provisioning_uri(secret, self.admin.username)
        return SetupInfo(secret=secret, otpauth_uri=uri, qr_svg=totp.qr_svg_data_uri(uri))

    def enable(self, code: str, current: AuthSession | None) -> list[str]:
        """Confirm the pending secret with a code; returns the new recovery codes."""
        if self.admin.totp_enabled:
            raise ApiError(409, "two_factor_already_enabled")
        if not self.admin.totp_pending_secret_encrypted:
            raise ApiError(409, "two_factor_setup_missing")
        secret = crypto.decrypt(self.admin.totp_pending_secret_encrypted)
        step = totp.verify(secret, code, None, utcnow().timestamp())
        if step is None:
            raise ApiError(422, "invalid_code", fields={"code": "invalid_code"})
        codes = totp.new_recovery_codes()
        self.admin.totp_secret_encrypted = self.admin.totp_pending_secret_encrypted
        self.admin.totp_pending_secret_encrypted = None
        self.admin.totp_enabled = True
        self.admin.totp_last_step = step
        self.admin.totp_recovery_hashes = [totp.hash_recovery_code(c) for c in codes]
        # Anyone else signed in with only the password is signed out.
        self._end_other_sessions(current)
        self.db.commit()
        logger.info("Two-factor authentication enabled for %r", self.admin.username)
        return codes

    def disable(self, password: str, code: str, current: AuthSession | None) -> None:
        self._require_password(password)
        if not self.admin.totp_enabled:
            raise ApiError(409, "two_factor_not_enabled")
        self._require_code(code)
        disable_two_factor(self.admin)
        self._end_other_sessions(current)
        self.db.commit()
        logger.warning("Two-factor authentication disabled for %r", self.admin.username)

    def regenerate_recovery_codes(self, password: str, code: str) -> list[str]:
        self._require_password(password)
        if not self.admin.totp_enabled:
            raise ApiError(409, "two_factor_not_enabled")
        self._require_code(code)
        codes = totp.new_recovery_codes()
        self.admin.totp_recovery_hashes = [totp.hash_recovery_code(c) for c in codes]
        self.db.commit()
        logger.info("New recovery codes generated for %r", self.admin.username)
        return codes


def disable_two_factor(admin: AdminAccount) -> None:
    admin.totp_enabled = False
    admin.totp_secret_encrypted = None
    admin.totp_pending_secret_encrypted = None
    admin.totp_last_step = None
    admin.totp_recovery_hashes = None
