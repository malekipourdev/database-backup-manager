"""Bot settings, admins and one-time link codes."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mbp.api.errors import ApiError
from mbp.bots.api import BotApi, BotApiError
from mbp.db import utcnow
from mbp.logging import register_secret
from mbp.models import BotAdmin, BotLinkCode, BotSettings
from mbp.models.bot import PLATFORMS
from mbp.repositories.bot_repository import BotRepository
from mbp.security import crypto

LINK_CODE_TTL = timedelta(minutes=15)
# Unambiguous characters (no 0/O, 1/I/L) so the code is easy to type on a phone.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def hash_code(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def decrypted_token(row: BotSettings) -> str | None:
    if not row.token_encrypted:
        return None
    token = crypto.decrypt(row.token_encrypted)
    register_secret(token)
    return token


def api_for(row: BotSettings, token: str | None = None, transport=None) -> BotApi | None:
    token = token or decrypted_token(row)
    if not token:
        return None
    return BotApi(
        row.platform,
        token,
        base_url=row.api_base_url,
        proxy=row.proxy_url,
        transport=transport,
    )


def check_platform(platform: str) -> None:
    if platform not in PLATFORMS:
        raise ApiError(404, "platform_not_found")


@dataclass(frozen=True)
class BotSettingsInput:
    enabled: bool
    # None or "" keeps the stored token.
    token: str | None
    api_base_url: str
    proxy_url: str
    allow_file_download: bool
    max_file_mb: int


@dataclass(frozen=True)
class BotTestResult:
    ok: bool
    username: str | None = None
    error_code: str | None = None
    error_detail: str | None = None


class BotService:
    def __init__(self, db: Session, transport=None) -> None:
        self.db = db
        self.repo = BotRepository(db)
        self.transport = transport

    # --- settings ---

    def update_settings(self, platform: str, data: BotSettingsInput) -> BotSettings:
        check_platform(platform)
        row = self.repo.get_settings_for_update(platform)
        if data.enabled and not (data.token or row.token_encrypted):
            raise ApiError(422, "validation_error", fields={"token": "required"})
        token_changed = bool(data.token)
        if data.token:
            register_secret(data.token)
            row.token_encrypted = crypto.encrypt(data.token)
        if token_changed or data.api_base_url != row.api_base_url:
            # Another bot (or server): its update numbering starts over.
            row.last_update_id = None
            row.bot_username = None
        row.enabled = data.enabled
        row.api_base_url = data.api_base_url
        row.proxy_url = data.proxy_url
        row.allow_file_download = data.allow_file_download
        row.max_file_mb = data.max_file_mb
        row.last_error = None
        self.db.commit()
        return row

    def clear_token(self, platform: str) -> BotSettings:
        check_platform(platform)
        row = self.repo.get_settings_for_update(platform)
        row.token_encrypted = None
        row.enabled = False
        row.bot_username = None
        row.last_update_id = None
        self.db.commit()
        return row

    def test(self, platform: str, data: BotSettingsInput) -> BotTestResult:
        """getMe with the given (possibly unsaved) values; an empty token uses the stored one."""
        check_platform(platform)
        row = self.repo.get_settings(platform)
        token = data.token or decrypted_token(row)
        if not token:
            raise ApiError(422, "validation_error", fields={"token": "required"})
        self.db.commit()
        api = BotApi(
            platform,
            token,
            base_url=data.api_base_url,
            proxy=data.proxy_url,
            transport=self.transport,
        )
        try:
            me = api.get_me()
        except BotApiError as exc:
            return BotTestResult(ok=False, error_code=exc.code, error_detail=exc.message)
        finally:
            api.close()
        return BotTestResult(ok=True, username=me.get("username"))

    # --- admins ---

    def add_admin(self, platform: str, user_id: int, display_name: str) -> BotAdmin:
        check_platform(platform)
        if self.repo.admin_by_user(platform, user_id) is not None:
            raise ApiError(409, "admin_exists", fields={"user_id": "admin_exists"})
        admin = BotAdmin(platform=platform, user_id=user_id, display_name=display_name)
        self.db.add(admin)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ApiError(409, "admin_exists", fields={"user_id": "admin_exists"}) from exc
        return admin

    def get_admin(self, admin_id: int) -> BotAdmin:
        admin = self.repo.admin(admin_id)
        if admin is None:
            raise ApiError(404, "admin_not_found")
        return admin

    def update_admin(
        self,
        admin_id: int,
        *,
        display_name: str | None = None,
        enabled: bool | None = None,
        notify_level: str | None = None,
        language: str | None = None,
    ) -> BotAdmin:
        admin = self.get_admin(admin_id)
        if display_name is not None:
            admin.display_name = display_name
        if enabled is not None:
            admin.enabled = enabled
        if notify_level is not None:
            admin.notify_level = notify_level
        if language is not None:
            admin.language = language
        self.db.commit()
        return admin

    def delete_admin(self, admin_id: int) -> None:
        self.db.delete(self.get_admin(admin_id))
        self.db.commit()

    # --- link codes ---

    def create_link_code(self, platform: str, display_name: str) -> tuple[str, datetime]:
        """A one-time code; whoever sends it to the bot within 15 minutes becomes an admin."""
        check_platform(platform)
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))
        expires = utcnow() + LINK_CODE_TTL
        self.db.add(
            BotLinkCode(
                platform=platform,
                code_hash=hash_code(code),
                display_name=display_name,
                expires_at=expires,
            )
        )
        self.db.commit()
        return code, expires

    def consume_link_code(self, platform: str, code: str, user_id: int) -> BotAdmin | None:
        """Register `user_id` if `code` is valid, unused and unexpired; None otherwise."""
        if len(code.strip()) != CODE_LENGTH:
            return None
        link = self.repo.link_code(platform, hash_code(code))
        now = utcnow()
        if link is None or link.used_at is not None or link.expires_at < now:
            return None
        link.used_at = now
        admin = self.repo.admin_by_user(platform, user_id)
        if admin is None:
            admin = BotAdmin(platform=platform, user_id=user_id, display_name=link.display_name)
            self.db.add(admin)
        admin.enabled = True
        self.db.commit()
        return admin
