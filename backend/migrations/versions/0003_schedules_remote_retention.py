"""schedules, remote storage and retention

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backup_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("cron", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("database_name", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_fired_at", UTCDateTime(), nullable=True),
        sa.Column("last_result", sa.String(length=32), nullable=True),
        sa.Column("last_detail", sa.Text(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"],
            ["db_instances.id"],
            name=op.f("fk_backup_schedules_instance_id_db_instances"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_schedules")),
    )
    op.create_index(op.f("ix_backup_schedules_instance_id"), "backup_schedules", ["instance_id"])

    remote = op.create_table(
        "remote_storage_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("endpoint_url", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=255), nullable=False),
        sa.Column("access_key_id", sa.String(length=255), nullable=False),
        sa.Column("secret_access_key_encrypted", sa.Text(), nullable=True),
        sa.Column("force_path_style", sa.Boolean(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_remote_storage_settings")),
    )
    op.bulk_insert(
        remote,
        [
            {
                "id": 1,
                "enabled": False,
                "provider": "s3",
                "endpoint_url": "",
                "region": "",
                "bucket": "",
                "prefix": "",
                "access_key_id": "",
                "secret_access_key_encrypted": None,
                "force_path_style": True,
                "updated_at": datetime.now(UTC),
            }
        ],
    )

    with op.batch_alter_table("backup_settings") as batch:
        batch.add_column(sa.Column("local_keep_last", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("local_max_age_days", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("remote_keep_last", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("remote_max_age_days", sa.Integer(), nullable=True))

    with op.batch_alter_table("db_instances") as batch:
        batch.add_column(sa.Column("remote_upload", sa.String(length=8), nullable=True))
        batch.add_column(
            sa.Column("retention_override", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("retention_local_keep_last", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("retention_local_max_age_days", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("retention_remote_keep_last", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("retention_remote_max_age_days", sa.Integer(), nullable=True))

    with op.batch_alter_table("backup_runs") as batch:
        batch.add_column(sa.Column("schedule_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("file_deleted_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("file_deleted_reason", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("remote_status", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("remote_key", sa.String(length=1024), nullable=True))
        batch.add_column(sa.Column("remote_uploaded_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("remote_deleted_at", UTCDateTime(), nullable=True))
        batch.add_column(sa.Column("remote_error", sa.Text(), nullable=True))
        batch.create_foreign_key(
            batch.f("fk_backup_runs_schedule_id_backup_schedules"),
            "backup_schedules",
            ["schedule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(batch.f("ix_backup_runs_schedule_id"), ["schedule_id"])
        batch.create_index(batch.f("ix_backup_runs_remote_status"), ["remote_status"])


def downgrade() -> None:
    with op.batch_alter_table("backup_runs") as batch:
        # The foreign key first: MySQL refuses to drop an index a foreign key still uses.
        batch.drop_constraint(
            batch.f("fk_backup_runs_schedule_id_backup_schedules"), type_="foreignkey"
        )
        batch.drop_index(batch.f("ix_backup_runs_remote_status"))
        batch.drop_index(batch.f("ix_backup_runs_schedule_id"))
        batch.drop_column("remote_error")
        batch.drop_column("remote_deleted_at")
        batch.drop_column("remote_uploaded_at")
        batch.drop_column("remote_key")
        batch.drop_column("remote_status")
        batch.drop_column("file_deleted_reason")
        batch.drop_column("file_deleted_at")
        batch.drop_column("schedule_id")

    with op.batch_alter_table("db_instances") as batch:
        batch.drop_column("retention_remote_max_age_days")
        batch.drop_column("retention_remote_keep_last")
        batch.drop_column("retention_local_max_age_days")
        batch.drop_column("retention_local_keep_last")
        batch.drop_column("retention_override")
        batch.drop_column("remote_upload")

    with op.batch_alter_table("backup_settings") as batch:
        batch.drop_column("remote_max_age_days")
        batch.drop_column("remote_keep_last")
        batch.drop_column("local_max_age_days")
        batch.drop_column("local_keep_last")

    op.drop_table("remote_storage_settings")
    # Dropping the table drops its index too (MySQL refuses to drop it first: the FK uses it).
    op.drop_table("backup_schedules")
