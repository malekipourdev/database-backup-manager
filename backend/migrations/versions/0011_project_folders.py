"""project folders: group projects in the panel's list

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("folder", sa.String(length=60), nullable=True))
        batch_op.create_index(batch_op.f("ix_projects_folder"), ["folder"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_projects_folder"))
        batch_op.drop_column("folder")
