from datetime import datetime

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class NotificationSettings(Base):
    """Alert rules, thresholds and the webhook channel; exactly one row with id 1."""

    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # {event: {"enabled": bool, "channels": ["bale", "telegram", "webhook"]}}; missing
    # events use the defaults in mbp.notifications.events.
    rules: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # The same alert about the same subject is sent at most once per this many minutes.
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # Alert when a marked database has had no successful backup for this many hours.
    stale_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=26)
    # Alert when free space in the backup area falls below this percentage.
    disk_free_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # "HH:MM" in `timezone`.
    daily_summary_time: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    # Used for the daily summary time and for times shown in messages.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Tehran")
    webhook_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    webhook_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # HMAC-SHA256 key for the X-MBP-Signature header; Fernet token, never returned.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class NotificationLog(Base):
    """Every alert raised, where it was delivered, and whether the cooldown suppressed it."""

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    # info | warning | error
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    # Dedupe key, e.g. "backup_failed:3:shop".
    subject: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # Values for the event's message template (no secrets).
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # {channel: "sent" | "failed: <reason>" | "no_recipients"}
    channels: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AlertState(Base):
    """A condition alert that is currently active (stale backup, low disk space).

    Present while the problem lasts, so it is announced once and its recovery once.
    """

    __tablename__ = "alert_states"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    active_since: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
