"""manual backups

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    settings = op.create_table(
        "backup_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("storage_dir", sa.String(length=255), nullable=False),
        sa.Column("name_pattern", sa.String(length=255), nullable=False),
        sa.Column("compression", sa.String(length=8), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_settings")),
    )
    op.bulk_insert(
        settings,
        [
            {
                "id": 1,
                "storage_dir": "",
                "name_pattern": "{instance}/{database}_{date}_{time}",
                "compression": "gzip",
                "updated_at": datetime.now(UTC),
            }
        ],
    )

    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.Integer(), nullable=True),
        sa.Column("instance_name", sa.String(length=100), nullable=False),
        sa.Column("database_name", sa.String(length=64), nullable=False),
        sa.Column("trigger", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("active_key", sa.String(length=200), nullable=True),
        sa.Column("requested_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("bytes_processed", sa.BigInteger(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("compression", sa.String(length=8), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("server_type", sa.String(length=16), nullable=True),
        sa.Column("server_version", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["db_instances.id"],
            name=op.f("fk_backup_runs_instance_id_db_instances"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_runs")),
        sa.UniqueConstraint("active_key", name=op.f("uq_backup_runs_active_key")),
    )
    op.create_index(op.f("ix_backup_runs_instance_id"), "backup_runs", ["instance_id"])
    op.create_index(op.f("ix_backup_runs_database_name"), "backup_runs", ["database_name"])
    op.create_index(op.f("ix_backup_runs_status"), "backup_runs", ["status"])
    op.create_index(op.f("ix_backup_runs_requested_at"), "backup_runs", ["requested_at"])

    with op.batch_alter_table("db_instances") as batch:
        batch.add_column(sa.Column("backup_storage_dir", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("backup_name_pattern", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("backup_compression", sa.String(length=8), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("db_instances") as batch:
        batch.drop_column("backup_compression")
        batch.drop_column("backup_name_pattern")
        batch.drop_column("backup_storage_dir")
    # Dropping the table drops its indexes too. MySQL refuses to drop ix_backup_runs_instance_id
    # on its own while the instance_id foreign key still uses it.
    op.drop_table("backup_runs")
    op.drop_table("backup_settings")
