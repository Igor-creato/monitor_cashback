"""add product feed tables

Revision ID: 20260613_0010
Revises: 20260613_0009
Create Date: 2026-06-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260613_0010"
down_revision: str | None = "20260613_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_feed_sources",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("merchant_id", sa.String(length=191), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("feed_url", sa.String(length=2048), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
        sa.Column("fields_mapping_json", sa.JSON(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
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
            "merchant_id",
            "source_code",
            "region_code",
            name="uq_product_feed_sources_identity",
        ),
    )
    op.create_table(
        "product_feed_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("feed_source_id", sa.BigInteger(), nullable=False),
        sa.Column("external_product_id", sa.String(length=191), nullable=True),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("old_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("category_id", sa.String(length=191), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["feed_source_id"],
            ["product_feed_sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "feed_source_id",
            "canonical_url",
            name="uq_product_feed_items_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("product_feed_items")
    op.drop_table("product_feed_sources")
