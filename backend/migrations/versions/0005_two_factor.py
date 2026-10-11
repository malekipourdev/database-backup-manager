"""two-factor authentication (TOTP)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("admin_accounts") as batch:
        batch.add_column(
            sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("totp_secret_encrypted", sa.Text(), nullable=True))
        batch.add_column(sa.Column("totp_pending_secret_encrypted", sa.Text(), nullable=True))
        batch.add_column(sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("totp_recovery_hashes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("admin_accounts") as batch:
        batch.drop_column("totp_recovery_hashes")
        batch.drop_column("totp_last_step")
        batch.drop_column("totp_pending_secret_encrypted")
        batch.drop_column("totp_secret_encrypted")
        batch.drop_column("totp_enabled")
