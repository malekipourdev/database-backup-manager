from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class WebServerSettings(Base):
    """How the panel manages and watches a server's web servers; one row per server."""

    __tablename__ = "webserver_settings"

    # The server's id.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Viewing only: every change (reload, edit, sites, certificates) is refused.
    read_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Alert when a certificate expires within this many days; 0 turns it off.
    cert_warning_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    # Health checks: how often, how long to wait, and failures in a row before an alert.
    check_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    check_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    check_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # Email given to Let's Encrypt for expiry notices (optional).
    acme_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class WebAction(Base):
    """Audit log: every change asked of a web server, by whom, and the outcome."""

    __tablename__ = "web_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    # panel | deploy
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    server_id: Mapped[int | None] = mapped_column(
        ForeignKey("servers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    server_name: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    # nginx | apache
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # reload | restart | edit | restore | enable | disable | maintenance_on | maintenance_off
    # | create | certbot_issue | certbot_renew | certbot_install
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # A file path or domain names.
    target: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # "ok", "running" (a certbot job), or an error code
    result: Mapped[str] = mapped_column(String(64), nullable=False)
    # The test / command output (trimmed).
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The agent's job, for certbot.
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


class WebCheck(Base):
    """A URL the panel requests regularly, and its current state."""

    __tablename__ = "web_checks"
    __table_args__ = (UniqueConstraint("server_id", "url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # up | down; NULL before the first check
    status: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Failed checks in a row.
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    down_since: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class WebCheckResult(Base):
    """One request of a check; the newest few hundred are kept."""

    __tablename__ = "web_check_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_id: Mapped[int] = mapped_column(
        ForeignKey("web_checks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)
