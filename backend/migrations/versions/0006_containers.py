"""containers: settings and the action audit log

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "container_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False),
        sa.Column("hidden", sa.JSON(), nullable=False),
        sa.Column("locked", sa.JSON(), nullable=False),
        sa.Column("monitor_all", sa.Boolean(), nullable=False),
        sa.Column("monitored", sa.JSON(), nullable=False),
        sa.Column("cpu_percent", sa.Integer(), nullable=False),
        sa.Column("memory_percent", sa.Integer(), nullable=False),
        sa.Column("restart_count", sa.Integer(), nullable=False),
        sa.Column("restart_window_minutes", sa.Integer(), nullable=False),
        sa.Column("host_memory_percent", sa.Integer(), nullable=False),
        sa.Column("host_disk_percent", sa.Integer(), nullable=False),
        sa.Column("bot_logs", sa.Boolean(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_container_settings")),
    )
    op.create_table(
        "container_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("container", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_container_actions")),
    )
    op.create_index(op.f("ix_container_actions_created_at"), "container_actions", ["created_at"])


def downgrade() -> None:
    op.drop_table("container_actions")
    op.drop_table("container_settings")
