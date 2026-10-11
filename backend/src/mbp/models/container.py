from datetime import datetime

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class ContainerSettings(Base):
    """How the panel shows, controls and watches the server's containers; one row, id 1."""

    __tablename__ = "container_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Monitoring only: start/stop/restart are refused everywhere.
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Name patterns (fnmatch, e.g. "vault*") of containers the panel does not show at all.
    hidden: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Name patterns of containers that are shown but cannot be started, stopped or restarted.
    locked: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Alerts for every visible container, or only for the names in `monitored`.
    monitor_all: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    monitored: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Alert thresholds; 0 turns a check off.
    cpu_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    memory_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    restart_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    restart_window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    host_memory_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    host_disk_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    # Container logs can hold sensitive data; showing them in a bot copies them to the
    # messenger's servers, so it is off unless an admin turns it on.
    bot_logs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class ContainerAction(Base):
    """Audit log: every start/stop/restart asked for, by whom, from where, and the outcome."""

    __tablename__ = "container_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    # Panel username, or the bot admin's display name.
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    # panel | bale | telegram
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    container: Mapped[str] = mapped_column(String(128), nullable=False)
    # start | stop | restart
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # "ok" or an error code
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
