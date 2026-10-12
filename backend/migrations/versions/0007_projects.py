"""projects and deployments

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("repo_url", sa.String(length=500), nullable=False),
        sa.Column("branch", sa.String(length=200), nullable=False),
        sa.Column("compose_file", sa.String(length=200), nullable=False),
        sa.Column("auth_type", sa.String(length=16), nullable=False),
        sa.Column("credential_encrypted", sa.Text(), nullable=True),
        sa.Column("env_encrypted", sa.Text(), nullable=True),
        sa.Column("backup_instance_id", sa.Integer(), nullable=True),
        sa.Column("backup_databases", sa.JSON(), nullable=False),
        sa.Column("backup_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["backup_instance_id"],
            ["db_instances.id"],
            name=op.f("fk_projects_backup_instance_id_db_instances"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("name", name=op.f("uq_projects_name")),
    )
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("project_name", sa.String(length=40), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("step", sa.String(length=16), nullable=True),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("commit_message", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=300), nullable=True),
        sa.Column("log", sa.Text(), nullable=False),
        sa.Column("backup_run_ids", sa.JSON(), nullable=False),
        sa.Column("requested_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_deployments_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deployments")),
    )
    op.create_index(op.f("ix_deployments_project_id"), "deployments", ["project_id"])
    op.create_index(op.f("ix_deployments_requested_at"), "deployments", ["requested_at"])


def downgrade() -> None:
    op.drop_table("deployments")
    op.drop_table("projects")
