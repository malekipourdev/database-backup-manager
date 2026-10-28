"""project folders as rows, so a folder can exist before its first project

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-28
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    folders = op.create_table(
        "project_folders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_folders")),
        sa.UniqueConstraint("name", name=op.f("uq_project_folders_name")),
    )
    # The folders projects already have.
    names = op.get_bind().execute(
        sa.text("SELECT DISTINCT folder FROM projects WHERE folder IS NOT NULL")
    )
    now = datetime.now(UTC)
    rows = [{"name": name, "created_at": now} for (name,) in names if name]
    if rows:
        op.bulk_insert(folders, rows)


def downgrade() -> None:
    op.drop_table("project_folders")
