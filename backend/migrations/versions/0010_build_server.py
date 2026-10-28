"""a project's build server: build there, run on the project's server

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("build_server_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_projects_build_server_id_servers"),
            "servers",
            ["build_server_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_projects_build_server_id_servers"), type_="foreignkey"
        )
        batch_op.drop_column("build_server_id")
