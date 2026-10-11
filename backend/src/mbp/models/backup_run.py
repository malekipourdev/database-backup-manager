from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow

ACTIVE_STATUSES = ("queued", "running")


class BackupRun(Base):
    """One attempt to back up one database of one instance."""

    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Kept (as NULL) when the instance is deleted; instance_name preserves the label.
    instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("db_instances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    instance_name: Mapped[str] = mapped_column(String(100), nullable=False)
    database_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # all | single
    trigger: Mapped[str] = mapped_column(String(8), nullable=False)
    # queued | running | success | failed
    status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # "<instance_id>:<database>" while queued/running, NULL afterwards. The unique
    # constraint prevents two active runs of the same database on every backend DB.
    active_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    bytes_processed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    compression: Mapped[str | None] = mapped_column(String(8), nullable=True)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Relative to the backup storage root.
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    server_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    server_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Sanitized, at most 1,000 characters, never contains secrets.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def __repr__(self) -> str:
        return f"BackupRun(id={self.id!r}, database={self.database_name!r}, status={self.status!r})"
