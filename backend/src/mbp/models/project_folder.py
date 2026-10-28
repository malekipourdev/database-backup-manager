from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class ProjectFolder(Base):
    """A folder of projects (Project.folder holds its name); it may be empty."""

    __tablename__ = "project_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
