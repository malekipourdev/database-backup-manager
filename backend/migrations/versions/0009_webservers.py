"""web servers: settings, audit log, health checks; a project's domains

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webserver_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("cert_warning_days", sa.Integer(), nullable=False),
        sa.Column("check_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("check_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("check_failures", sa.Integer(), nullable=False),
        sa.Column("acme_email", sa.String(length=254), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webserver_settings")),
    )
    op.create_table(
        "web_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=True),
        sa.Column("server_name", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=500), nullable=False),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("job_id", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_web_actions_server_id_servers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_actions")),
    )
    with op.batch_alter_table("web_actions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_web_actions_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_web_actions_server_id"), ["server_id"], unique=False)

    op.create_table(
        "web_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_checked_at", UTCDateTime(), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=True),
        sa.Column("last_code", sa.Integer(), nullable=True),
        sa.Column("last_ms", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("down_since", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["server_id"],
            ["servers.id"],
            name=op.f("fk_web_checks_server_id_servers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_checks")),
        sa.UniqueConstraint("server_id", "url", name=op.f("uq_web_checks_server_id")),
    )
    with op.batch_alter_table("web_checks", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_web_checks_server_id"), ["server_id"], unique=False)

    op.create_table(
        "web_check_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("check_id", sa.Integer(), nullable=False),
        sa.Column("checked_at", UTCDateTime(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("code", sa.Integer(), nullable=True),
        sa.Column("ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(
            ["check_id"],
            ["web_checks.id"],
            name=op.f("fk_web_check_results_check_id_web_checks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_web_check_results")),
    )
    with op.batch_alter_table("web_check_results", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_web_check_results_check_id"), ["check_id"], unique=False
        )

    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("web_domains", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("web_target", sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_column("web_target")
        batch_op.drop_column("web_domains")

    # Dropping a table drops its indexes; MySQL refuses to drop an index a foreign key still needs.
    op.drop_table("web_check_results")
    op.drop_table("web_checks")
    op.drop_table("web_actions")
    op.drop_table("webserver_settings")
