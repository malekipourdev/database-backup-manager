"""The external API: keys other software uses to drive the panel, and webhooks it listens on."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class ApiSettings(Base):
    """Switches for the whole external API; exactly one row with id 1."""

    __tablename__ = "api_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Off: every key is refused (the documentation stays reachable).
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Browser origins allowed to call the API directly (CORS), e.g. "https://app.example.com";
    # "*" allows any origin. Empty: only server-to-server calls.
    cors_origins: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Request log entries older than this are deleted.
    log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class ApiKey(Base):
    """A key for the external API. Only the SHA-256 of the secret is stored."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # The first characters of the secret ("mbp_ab12cd34"), to recognise a key; not secret.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # "<area>:read" | "<area>:write" | "backups:download" | "*"; see mbp.apiaccess.scopes.
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Addresses or networks (CIDR) the key may be used from; empty: anywhere.
    allowed_ips: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # The servers the key reaches (what is on them and what belongs to them); null: every
    # server, and the panel-wide settings. See mbp.apiaccess.servers.
    server_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Requests per minute; 0: unlimited.
    rate_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # The key acts as this admin (audit entries name both).
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_used_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    request_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ApiRequestLog(Base):
    """One request made with a key (successful or refused)."""

    __tablename__ = "api_request_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key_id: Mapped[int] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The error code of a refused or failed request.
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The person the calling software acted for (its X-MBP-On-Behalf-Of header).
    on_behalf_of: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ApiWebhook(Base):
    """An address that receives events (backup failed, deploy finished, ...) as signed JSON."""

    __tablename__ = "api_webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Event names, or ["*"] for every event.
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Only events about these servers; null: every event (also the panel-wide ones).
    server_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # HMAC-SHA256 key of the X-MBP-Signature header; Fernet token.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Failed deliveries in a row (0 after a successful one).
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class ApiWebhookDelivery(Base):
    """One event sent (or being sent) to a webhook, with its retries."""

    __tablename__ = "api_webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("api_webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The X-MBP-Delivery header and the payload's "id".
    uuid: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # pending | sent | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Why the last attempt failed, or the start of the response body.
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
