from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class BackupSchedule(Base):
    """A cron schedule that queues backups of one instance."""

    __tablename__ = "backup_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("db_instances.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Standard 5-field crontab expression, evaluated in `timezone`.
    cron: Mapped[str] = mapped_column(String(100), nullable=False)
    # IANA time zone name, e.g. "UTC" or "Asia/Tehran".
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # all (every marked database) | single (database_name)
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    database_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # queued | partially_queued | already_in_progress | no_databases_selected | error
    last_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"BackupSchedule(id={self.id!r}, cron={self.cron!r}, enabled={self.enabled!r})"
