from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class RemoteStorageSettings(Base):
    """Remote (S3-compatible) storage target; exactly one row with id 1."""

    __tablename__ = "remote_storage_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Upload every backup by default; instances may opt in or out.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="s3")
    # Empty means AWS S3; otherwise the S3-compatible endpoint (MinIO, Ceph, Arvan, ...).
    endpoint_url: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    bucket: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Key prefix inside the bucket; "" stores objects at the bucket root.
    prefix: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    access_key_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Fernet token; never returned or logged.
    secret_access_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_path_style: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
