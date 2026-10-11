from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow

DEFAULT_STORAGE_DIR = ""
DEFAULT_NAME_PATTERN = "{instance}/{database}_{date}_{time}"
DEFAULT_COMPRESSION = "gzip"


class BackupSettings(Base):
    """Global backup defaults; exactly one row with id 1."""

    __tablename__ = "backup_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Relative to the backup storage root; "" is the root itself.
    storage_dir: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    name_pattern: Mapped[str] = mapped_column(
        String(255), nullable=False, default=DEFAULT_NAME_PATTERN
    )
    # gzip | bzip2 | none
    compression: Mapped[str] = mapped_column(String(8), nullable=False, default="gzip")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
