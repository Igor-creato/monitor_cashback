"""add price comparison tables

Revision ID: 20260703_0006
Revises: 20260703_0005
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_0006"
down_revision: str | None = "20260703_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_compare_store_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="custom"),
        sa.Column("source_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("logo_url", sa.String(length=2048), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("supports_region", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "fallback_behavior",
            sa.String(length=64),
            nullable=False,
            server_default="status_only",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("domain", name="uq_price_compare_store_sources_domain"),
    )
    op.create_index(
        "ix_price_compare_store_sources_domain",
        "price_compare_store_sources",
        ["domain"],
    )

    op.create_table(
        "price_compare_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("store_domain", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("normalized_title", sa.String(length=1024), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("availability", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("region_supported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("raw_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["store_domain"],
            ["price_compare_store_sources.domain"],
            name="fk_price_compare_offers_store_domain",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_price_compare_offers_store_domain", "price_compare_offers", ["store_domain"]
    )
    op.create_index(
        "ix_price_compare_offers_normalized_title",
        "price_compare_offers",
        ["normalized_title"],
    )
    op.create_unique_constraint(
        "uq_price_compare_offers_source_external_url",
        "price_compare_offers",
        ["source", "external_id", "url"],
    )

    op.create_table(
        "price_compare_import_statuses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("store_domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="idle"),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_price_compare_import_statuses_store_domain",
        "price_compare_import_statuses",
        ["store_domain"],
    )
    op.create_unique_constraint(
        "uq_price_compare_import_statuses_source_store",
        "price_compare_import_statuses",
        ["source", "store_domain"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_price_compare_import_statuses_source_store",
        "price_compare_import_statuses",
        type_="unique",
    )
    op.drop_index(
        "ix_price_compare_import_statuses_store_domain",
        table_name="price_compare_import_statuses",
    )
    op.drop_table("price_compare_import_statuses")
    op.drop_constraint(
        "uq_price_compare_offers_source_external_url",
        "price_compare_offers",
        type_="unique",
    )
    op.drop_index("ix_price_compare_offers_normalized_title", table_name="price_compare_offers")
    op.drop_index("ix_price_compare_offers_store_domain", table_name="price_compare_offers")
    op.drop_table("price_compare_offers")
    op.drop_index("ix_price_compare_store_sources_domain", table_name="price_compare_store_sources")
    op.drop_table("price_compare_store_sources")
