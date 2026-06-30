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

    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("image_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("rating_value", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("current_price_minor", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("currency", sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column("last_fetch_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
    op.execute("UPDATE products SET updated_at = created_at WHERE updated_at IS NULL")

    with op.batch_alter_table("watchlist_items") as batch_op:
        batch_op.add_column(sa.Column("active_identity_key", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
    op.execute("UPDATE watchlist_items SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute(
        "UPDATE watchlist_items "
        "SET active_identity_key = user_id || ':' || canonical_url_hash "
        "WHERE status = 'active' AND active_identity_key IS NULL"
    )
    with op.batch_alter_table("watchlist_items") as batch_op:
        batch_op.drop_constraint("uq_watchlist_user_url_hash", type_="unique")
        batch_op.create_unique_constraint(
            "uq_watchlist_items_active_identity_key", ["active_identity_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("watchlist_items") as batch_op:
        batch_op.drop_constraint("uq_watchlist_items_active_identity_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_watchlist_user_url_hash", ["user_id", "canonical_url_hash"]
        )
        batch_op.drop_column("updated_at")
        batch_op.drop_column("active_identity_key")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("last_fetched_at")
        batch_op.drop_column("last_fetch_status")
        batch_op.drop_column("currency")
        batch_op.drop_column("current_price_minor")
        batch_op.drop_column("rating_value")
        batch_op.drop_column("image_url")
    op.drop_index("ix_proxy_endpoints_tier", table_name="proxy_endpoints")
    op.drop_index("ix_proxy_endpoints_status", table_name="proxy_endpoints")
    op.drop_index("ix_proxy_endpoints_pool_id", table_name="proxy_endpoints")
    op.drop_table("proxy_endpoints")
    op.drop_index("ix_proxy_pools_status", table_name="proxy_pools")
    op.drop_table("proxy_pools")
    op.drop_table("monitor_settings")
    op.drop_index("ix_monitored_sources_status", table_name="monitored_sources")
    op.drop_table("monitored_sources")
