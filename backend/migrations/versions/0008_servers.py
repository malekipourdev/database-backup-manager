"""servers: several machines managed by one panel

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from mbp.db import UTCDateTime

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    servers = op.create_table(
        "servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("name_normalized", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("cert_pem", sa.Text(), nullable=True),
        sa.Column("cert_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("paired_at", UTCDateTime(), nullable=True),
        sa.Column("last_seen_at", UTCDateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("agent_hostname", sa.String(length=255), nullable=True),
        sa.Column("docker_version", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_servers")),
        sa.UniqueConstraint("name_normalized", name=op.f("uq_servers_name_normalized")),
    )
    now = datetime.now(UTC)
    # Without an explicit id, so PostgreSQL's sequence stays in step.
    op.bulk_insert(
        servers,
        [
            {
                "name": "main",
                "name_normalized": "main",
                "kind": "local",
                "notes": "",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    conn = op.get_bind()
    local_id = conn.execute(sa.text("SELECT id FROM servers WHERE kind = 'local'")).scalar_one()
    if local_id != 1:
        # Container settings rows are keyed by their server's id.
        conn.execute(
            sa.text("UPDATE container_settings SET id = :local WHERE id = 1"), {"local": local_id}
        )

    with op.batch_alter_table("db_instances") as batch:
        batch.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            batch.f("fk_db_instances_server_id_servers"),
            "servers",
            ["server_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(batch.f("ix_db_instances_server_id"), ["server_id"])

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
    conn.execute(sa.text("UPDATE projects SET server_id = :local"), {"local": local_id})
    with op.batch_alter_table("projects") as batch:
        batch.alter_column("server_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            batch.f("fk_projects_server_id_servers"),
            "servers",
            ["server_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index(batch.f("ix_projects_server_id"), ["server_id"])

    with op.batch_alter_table("container_actions") as batch:
        batch.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("server_name", sa.String(length=60), nullable=False, server_default="")
        )
        batch.create_foreign_key(
            batch.f("fk_container_actions_server_id_servers"),
            "servers",
            ["server_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(batch.f("ix_container_actions_server_id"), ["server_id"])
    conn.execute(
        sa.text("UPDATE container_actions SET server_id = :local, server_name = 'main'"),
        {"local": local_id},
    )


def downgrade() -> None:
    conn = op.get_bind()
    # Only the local server's data fits the single-server schema.
    local_id = conn.execute(sa.text("SELECT id FROM servers WHERE kind = 'local'")).scalar()
    conn.execute(
        sa.text("DELETE FROM container_settings WHERE id <> :local"), {"local": local_id or 1}
    )
    if local_id and local_id != 1:
        conn.execute(
            sa.text("UPDATE container_settings SET id = 1 WHERE id = :local"), {"local": local_id}
        )
    with op.batch_alter_table("container_actions") as batch:
        batch.drop_constraint(batch.f("fk_container_actions_server_id_servers"), type_="foreignkey")
        batch.drop_index(batch.f("ix_container_actions_server_id"))
        batch.drop_column("server_name")
        batch.drop_column("server_id")
    conn.execute(
        sa.text("DELETE FROM projects WHERE server_id <> :local"), {"local": local_id or 0}
    )
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint(batch.f("fk_projects_server_id_servers"), type_="foreignkey")
        batch.drop_index(batch.f("ix_projects_server_id"))
        batch.drop_column("server_id")
    with op.batch_alter_table("db_instances") as batch:
        batch.drop_constraint(batch.f("fk_db_instances_server_id_servers"), type_="foreignkey")
        batch.drop_index(batch.f("ix_db_instances_server_id"))
        batch.drop_column("server_id")
    op.drop_table("servers")
