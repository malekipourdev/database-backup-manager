from datetime import datetime, timedelta

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow

ACTIVE_STATUSES = ("queued", "running")
# A remote copy can't be deleted by the panel (retention or by hand) until this long after
# its upload. Within that window it can only be deleted in the storage provider itself.
REMOTE_PROTECTION = timedelta(days=7)


class BackupRun(Base):
    """One attempt to back up one database of one instance."""

    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Kept (as NULL) when the instance is deleted; instance_name preserves the label.
    instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("db_instances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    instance_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # The schedule that queued this run (trigger "schedule"); NULL once it is deleted.
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("backup_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    database_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # all | single | schedule
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
    # Set when the local file was removed by retention; the run record is kept.
    file_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # retention | manual (deleted by an admin while the remote copy was kept)
    file_deleted_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # NULL (not uploaded) | uploading | success | failed | deleted
    remote_status: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    # Object key in the remote bucket.
    remote_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    remote_uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    remote_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Sanitized, never contains secrets.
    remote_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def has_local_file(self) -> bool:
        return self.status == "success" and bool(self.file_path) and self.file_deleted_at is None

    @property
    def has_remote_copy(self) -> bool:
        return self.remote_status == "success" and bool(self.remote_key)

    @property
    def remote_deletable_at(self) -> datetime | None:
        """When the panel may delete the remote copy (None if there is no remote copy)."""
        if not self.has_remote_copy:
            return None
        stored = self.remote_uploaded_at or self.finished_at or self.requested_at
        return stored + REMOTE_PROTECTION

    def remote_deletable(self, now: datetime) -> bool:
        deletable_at = self.remote_deletable_at
        return deletable_at is not None and now >= deletable_at

    def __repr__(self) -> str:
        return f"BackupRun(id={self.id!r}, database={self.database_name!r}, status={self.status!r})"
