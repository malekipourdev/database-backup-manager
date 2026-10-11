from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stored lower-cased, 1-64 chars.
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Argon2id hash; never exposed.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Two-factor authentication (TOTP, e.g. Google Authenticator).
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Fernet tokens of the base32 secrets; never returned or logged.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Secret being set up, until the admin confirms it with a code.
    totp_pending_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last accepted 30-second time step: a code is accepted once only.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # SHA-256 hashes of unused one-time recovery codes.
    totp_recovery_hashes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"AdminAccount(id={self.id!r}, username={self.username!r})"
