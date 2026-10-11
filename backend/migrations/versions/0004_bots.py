"""messenger bots (Bale, Telegram) and notifications

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    settings = op.create_table(
        "bot_settings",
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("api_base_url", sa.String(length=255), nullable=False),
        sa.Column("proxy_url", sa.String(length=255), nullable=False),
        sa.Column("allow_file_download", sa.Boolean(), nullable=False),
        sa.Column("max_file_mb", sa.Integer(), nullable=False),
        sa.Column("bot_username", sa.String(length=64), nullable=True),
        sa.Column("last_update_id", sa.BigInteger(), nullable=True),
        sa.Column("last_ok_at", UTCDateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("platform", name=op.f("pk_bot_settings")),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        settings,
        [
            {
                "platform": platform,
                "enabled": False,
                "token_encrypted": None,
                "api_base_url": "",
                "proxy_url": "",
                "allow_file_download": False,
                "max_file_mb": max_mb,
                "bot_username": None,
                "last_update_id": None,
                "last_ok_at": None,
                "last_error": None,
                "updated_at": now,
            }
            for platform, max_mb in (("bale", 20), ("telegram", 50))
        ],
    )
    op.create_table(
        "bot_admins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notify_level", sa.String(length=8), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("last_seen_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_admins")),
        sa.UniqueConstraint("platform", "user_id", name=op.f("uq_bot_admins_platform")),
    )
    op.create_table(
        "bot_link_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("used_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bot_link_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_bot_link_codes_code_hash")),
    )

    notification = op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False),
        sa.Column("stale_hours", sa.Integer(), nullable=False),
        sa.Column("disk_free_percent", sa.Integer(), nullable=False),
        sa.Column("daily_summary_time", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("webhook_enabled", sa.Boolean(), nullable=False),
        sa.Column("webhook_url", sa.String(length=500), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_settings")),
    )
    op.bulk_insert(
        notification,
        [
            {
                "id": 1,
                "rules": {},
                "cooldown_minutes": 60,
                "stale_hours": 26,
                "disk_free_percent": 10,
                "daily_summary_time": "08:00",
                "timezone": "Asia/Tehran",
                "webhook_enabled": False,
                "webhook_url": "",
                "webhook_secret_encrypted": None,
                "updated_at": now,
            }
        ],
    )
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("suppressed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_log")),
    )
    op.create_index(op.f("ix_notification_log_created_at"), "notification_log", ["created_at"])
    op.create_index(op.f("ix_notification_log_subject"), "notification_log", ["subject"])
    op.create_table(
        "alert_states",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("active_since", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_alert_states")),
    )


def downgrade() -> None:
    op.drop_table("alert_states")
    op.drop_table("notification_log")
    op.drop_table("notification_settings")
    op.drop_table("bot_link_codes")
    op.drop_table("bot_admins")
    op.drop_table("bot_settings")
