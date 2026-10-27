from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from mbp.db import Base, UTCDateTime, utcnow


class Project(Base):
    """An application deployed from a git repository with docker compose, by the agent."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Also the compose project name and the directory name: [a-z0-9][a-z0-9_-]{0,39}.
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    # The server it is deployed on.
    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    branch: Mapped[str] = mapped_column(String(200), nullable=False, default="main")
    compose_file: Mapped[str] = mapped_column(
        String(200), nullable=False, default="docker-compose.yml"
    )
    # none | token | ssh_key
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    # Fernet token of the access token or SSH private key; never returned or logged.
    credential_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Fernet token of a JSON object {name: value}: written to the project's .env on deploy.
    env_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Databases backed up before every deploy (on this instance), and whether a failed
    # backup stops the deploy.
    backup_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("db_instances.id", ondelete="SET NULL"), nullable=True
    )
    backup_databases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    backup_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # After a successful deploy, these domains are served by a reverse proxy to `web_target`
    # (e.g. http://127.0.0.1:8080) on the server's web server, unless a site has them already.
    web_domains: Mapped[list | None] = mapped_column(JSON, nullable=True)
    web_target: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class Deployment(Base):
    """One deploy of a project: who asked, which commit, each step's outcome and the log."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL once the project is deleted; the history keeps its name.
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_name: Mapped[str] = mapped_column(String(40), nullable=False)
    # panel | bale | telegram
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    # The branch, tag or commit asked for (a commit for "redeploy this version").
    ref: Mapped[str] = mapped_column(String(200), nullable=False)
    # queued | running | success | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    # backup | fetch | build | up | check
    step: Mapped[str | None] = mapped_column(String(16), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    commit_message: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Secrets are masked by the agent before the log leaves it.
    log: Mapped[str] = mapped_column(Text, nullable=False, default="")
    backup_run_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
