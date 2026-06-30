"""price monitor vertical slice

Revision ID: 20260630_0002
Revises: 20260629_0001
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260630_0002"
down_revision: str | None = "20260629_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitored_sources",
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("logo_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fetch_interval_hours", sa.Integer(), nullable=False),
        sa.Column("history_retention_days", sa.Integer(), nullable=False),
        sa.Column("browser_fallback_allowed", sa.Boolean(), nullable=False),
        sa.Column("proxy_pool_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_domain"),
    )
    op.create_index("ix_monitored_sources_status", "monitored_sources", ["status"])

    op.create_table(
        "monitor_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "proxy_pools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_proxy_pools_status", "proxy_pools", ["status"])

    op.create_table(
        "proxy_endpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pool_id", sa.String(length=36), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("proxy_url_secret_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pool_id"], ["proxy_pools.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_proxy_endpoints_pool_id", "proxy_endpoints", ["pool_id"])
    op.create_index("ix_proxy_endpoints_status", "proxy_endpoints", ["status"])
    op.create_index("ix_proxy_endpoints_tier", "proxy_endpoints", ["tier"])


def downgrade() -> None:
    op.drop_index("ix_proxy_endpoints_tier", table_name="proxy_endpoints")
    op.drop_index("ix_proxy_endpoints_status", table_name="proxy_endpoints")
    op.drop_index("ix_proxy_endpoints_pool_id", table_name="proxy_endpoints")
    op.drop_table("proxy_endpoints")
    op.drop_index("ix_proxy_pools_status", table_name="proxy_pools")
    op.drop_table("proxy_pools")
    op.drop_table("monitor_settings")
    op.drop_index("ix_monitored_sources_status", table_name="monitored_sources")
    op.drop_table("monitored_sources")
