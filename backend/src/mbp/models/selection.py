from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mbp.db import Base, UTCDateTime, utcnow

if TYPE_CHECKING:
    from mbp.models.instance import DbInstance


class DbSelection(Base):
    """A database on an instance that is included in backups."""

    __tablename__ = "db_selections"
    __table_args__ = (UniqueConstraint("instance_id", "database_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[int] = mapped_column(
        ForeignKey("db_instances.id", ondelete="CASCADE"), nullable=False
    )
    database_name: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)

    instance: Mapped["DbInstance"] = relationship(back_populates="selections")
