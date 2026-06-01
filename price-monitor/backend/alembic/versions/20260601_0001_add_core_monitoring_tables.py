"""add core monitoring tables

Revision ID: 20260601_0001
Revises:
Create Date: 2026-06-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260601_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracked_products",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_product_id", sa.String(length=191), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
        sa.Column("variant_hash", sa.String(length=128), nullable=True),
        sa.Column("product_name", sa.String(length=512), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("last_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("last_old_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "last_availability",
            sa.Boolean(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "external_product_id",
            "region_code",
            "variant_hash",
            name="uq_tracked_products_identity",
        ),
    )
    op.create_table(
        "user_product_subscriptions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("tracked_product_id", sa.BigInteger(), nullable=False),
        sa.Column("target_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("target_effective_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id",
            "external_user_id",
            "tracked_product_id",
            name="uq_user_product_subscriptions_identity",
        ),
    )
    op.create_table(
        "price_history",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tracked_product_id", sa.BigInteger(), nullable=False),
        sa.Column("price_current", sa.Numeric(12, 2), nullable=False),
        sa.Column("price_old", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("availability", sa.Boolean(), nullable=False),
        sa.Column("seller_name", sa.String(length=255), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "fetch_jobs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tracked_product_id", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="5", nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("fetch_jobs")
    op.drop_table("price_history")
    op.drop_table("user_product_subscriptions")
    op.drop_table("tracked_products")
