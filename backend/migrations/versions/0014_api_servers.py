"""external API: keys and webhooks limited to some servers; who a request was made for

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.add_column(sa.Column("server_ids", sa.JSON(), nullable=True))
    with op.batch_alter_table("api_webhooks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("server_ids", sa.JSON(), nullable=True))
    with op.batch_alter_table("api_request_log", schema=None) as batch_op:
        batch_op.add_column(sa.Column("on_behalf_of", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("api_request_log", schema=None) as batch_op:
        batch_op.drop_column("on_behalf_of")
    with op.batch_alter_table("api_webhooks", schema=None) as batch_op:
        batch_op.drop_column("server_ids")
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_column("server_ids")
