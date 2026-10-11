from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mbp.db import Base, UTCDateTime, utcnow

if TYPE_CHECKING:
    from mbp.models.selection import DbSelection


class DbInstance(Base):
    __tablename__ = "db_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Lower-cased name; enforces case-insensitive uniqueness.
    name_normalized: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=3306)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet token; never returned or logged.
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    server_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    server_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Backup setting overrides; NULL means "inherit the global value".
    backup_storage_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backup_name_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)
    backup_compression: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Remote upload: NULL inherits the global setting, else "enabled" | "disabled".
    remote_upload: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # When true, the retention_* columns replace the global retention policy.
    retention_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retention_local_keep_last: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_local_max_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_remote_keep_last: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_remote_max_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )

    selections: Mapped[list["DbSelection"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DbSelection.database_name",
    )

    def __repr__(self) -> str:
        return f"DbInstance(id={self.id!r}, name={self.name!r}, host={self.host!r})"
