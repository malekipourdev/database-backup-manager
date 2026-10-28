"""external API: keys, request log, settings, webhooks and their deliveries

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cors_origins", sa.JSON(), nullable=False),
        sa.Column("log_retention_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_settings")),
    )
    op.create_table(
        "api_webhooks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("last_delivery_at", UTCDateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=100), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_webhooks")),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("allowed_ips", sa.JSON(), nullable=False),
        sa.Column("rate_limit", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=True),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.Column("last_used_ip", sa.String(length=45), nullable=True),
        sa.Column("request_count", sa.BigInteger(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("rotated_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_accounts.id"],
            name=op.f("fk_api_keys_admin_id_admin_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("secret_hash", name=op.f("uq_api_keys_secret_hash")),
    )
    op.create_table(
        "api_webhook_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["api_webhooks.id"],
            name=op.f("fk_api_webhook_deliveries_webhook_id_api_webhooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_webhook_deliveries")),
    )
    with op.batch_alter_table("api_webhook_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_api_webhook_deliveries_webhook_id"), ["webhook_id"], unique=False
        )

    op.create_table(
        "api_request_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["key_id"],
            ["api_keys.id"],
            name=op.f("fk_api_request_log_key_id_api_keys"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_request_log")),
    )
    with op.batch_alter_table("api_request_log", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_api_request_log_created_at"), ["created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_api_request_log_key_id"), ["key_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("api_request_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_request_log_key_id"))
        batch_op.drop_index(batch_op.f("ix_api_request_log_created_at"))

    op.drop_table("api_request_log")
    with op.batch_alter_table("api_webhook_deliveries", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_webhook_deliveries_webhook_id"))

    op.drop_table("api_webhook_deliveries")
    op.drop_table("api_keys")
    op.drop_table("api_webhooks")
    op.drop_table("api_settings")
