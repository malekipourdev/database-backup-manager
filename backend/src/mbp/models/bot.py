from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow

PLATFORMS = ("bale", "telegram")


class BotSettings(Base):
    """One messenger bot (Bale or Telegram) that admins can use to manage backups."""

    __tablename__ = "bot_settings"

    # bale | telegram
    platform: Mapped[str] = mapped_column(String(16), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Fernet token of the bot token; never returned or logged.
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Empty means the platform's public Bot API.
    api_base_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Optional http(s):// or socks5:// proxy for reaching the Bot API.
    proxy_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Sending backup files through the bot copies database data to the messenger's servers.
    allow_file_download: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_file_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Offset for long polling (getUpdates).
    last_update_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Sanitized, never contains the token.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class BotAdmin(Base):
    """A messenger user allowed to use a bot. Nobody else gets any answer but their own ID."""

    __tablename__ = "bot_admins"
    __table_args__ = (UniqueConstraint("platform", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    # The messenger's numeric user ID (also the private chat ID).
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Lowest alert severity this admin receives: info | warning | error | off
    notify_level: Mapped[str] = mapped_column(String(8), nullable=False, default="warning")
    # fa | en
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="fa")
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class BotLinkCode(Base):
    """A one-time code an admin sends to the bot to register their own account."""

    __tablename__ = "bot_link_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    # SHA-256 of the code; the code itself is shown once in the panel.
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
