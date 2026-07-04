"""add affiliate feed source tables

Revision ID: 20260704_0008
Revises: 20260703_0007
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260704_0008"
down_revision: str | None = "20260703_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_compare_affiliate_feed_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("network", sa.String(length=32), nullable=False),
        sa.Column("store_domain", sa.String(length=255), nullable=False),
        sa.Column("offer_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("feed_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("format", sa.String(length=32), nullable=False, server_default="xml"),
        sa.Column("feed_url_hash", sa.String(length=64), nullable=True),
        sa.Column("feed_url_secret", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("descriptor_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_feed_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_domain"],
            ["price_compare_store_sources.domain"],
            name="fk_price_compare_affiliate_feed_sources_store_domain",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "network",
            "store_domain",
            "offer_id",
            "feed_id",
            name="uq_price_compare_affiliate_feed_identity",
        ),
    )
    op.create_index(
        "ix_price_compare_affiliate_feed_sources_network",
        "price_compare_affiliate_feed_sources",
        ["network"],
    )
    op.create_index(
        "ix_price_compare_affiliate_feed_sources_store_domain",
        "price_compare_affiliate_feed_sources",
        ["store_domain"],
    )

    op.create_table(
        "price_compare_feed_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feed_source_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feed_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quarantined_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["feed_source_id"],
            ["price_compare_affiliate_feed_sources.id"],
            name="fk_price_compare_feed_import_runs_feed_source_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_price_compare_feed_import_runs_feed_source_id",
        "price_compare_feed_import_runs",
        ["feed_source_id"],
    )

    op.create_table(
        "price_compare_price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("availability", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["price_compare_offers.id"],
            name="fk_price_compare_price_snapshots_offer_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_price_compare_price_snapshots_offer_id",
        "price_compare_price_snapshots",
        ["offer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_compare_price_snapshots_offer_id",
        table_name="price_compare_price_snapshots",
    )
    op.drop_table("price_compare_price_snapshots")
    op.drop_index(
        "ix_price_compare_feed_import_runs_feed_source_id",
        table_name="price_compare_feed_import_runs",
    )
    op.drop_table("price_compare_feed_import_runs")
    op.drop_index(
        "ix_price_compare_affiliate_feed_sources_store_domain",
        table_name="price_compare_affiliate_feed_sources",
    )
    op.drop_index(
        "ix_price_compare_affiliate_feed_sources_network",
        table_name="price_compare_affiliate_feed_sources",
    )
    op.drop_table("price_compare_affiliate_feed_sources")
