"""add price assistant foundation

Revision ID: 20260615_0014
Revises: 20260615_0013
Create Date: 2026-06-15 00:14:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0014"
down_revision: str | None = "20260615_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_regions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("region_code", sa.String(length=64), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="0", nullable=False),
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
            "site_id",
            "external_user_id",
            "region_code",
            name="uq_user_regions_identity",
        ),
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("store_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("homepage_url", sa.String(length=2048), nullable=True),
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
        sa.UniqueConstraint("store_code", name="uq_stores_store_code"),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=191), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope",
            "idempotency_key",
            name="uq_idempotency_records_key",
        ),
    )
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
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
            "site_id",
            "external_user_id",
            "event_type",
            "channel",
            name="uq_notification_preferences_identity",
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=True),
        sa.Column("external_user_id", sa.String(length=191), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=191), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "store_sources",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "source_type", sa.String(length=32), server_default="feed", nullable=False
        ),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "store_id",
            "source_code",
            name="uq_store_sources_store_source",
        ),
    )
    op.create_table(
        "imported_collections",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=True),
        sa.Column("collection_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="active", nullable=False
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
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
            ["connection_id"],
            ["marketplace_connections.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id",
            "external_user_id",
            "source",
            "collection_type",
            name="uq_imported_collections_owner_source_type",
        ),
    )
    op.create_table(
        "product_match_groups",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tracked_product_id", sa.BigInteger(), nullable=False),
        sa.Column("match_key", sa.String(length=191), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
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
            "tracked_product_id",
            "match_key",
            name="uq_product_match_groups_product_key",
        ),
    )
    op.create_table(
        "marketplace_sync_sessions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("collection_id", sa.BigInteger(), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("collection_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default="running", nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("item_count", sa.Integer(), server_default="0", nullable=False),
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
            ["collection_id"],
            ["imported_collections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["marketplace_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "product_offers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("match_group_id", sa.BigInteger(), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("external_product_id", sa.String(length=191), nullable=False),
        sa.Column("product_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("availability", sa.String(length=32), nullable=False),
        sa.Column("delivery_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "expected_cashback", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column("effective_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("match_confidence", sa.String(length=16), nullable=False),
        sa.Column("match_label", sa.String(length=32), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["match_group_id"],
            ["product_match_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_group_id",
            "store_id",
            "external_product_id",
            name="uq_product_offers_identity",
        ),
    )
    op.create_table(
        "imported_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("collection_id", sa.BigInteger(), nullable=False),
        sa.Column("sync_session_id", sa.BigInteger(), nullable=True),
        sa.Column("external_item_id", sa.String(length=191), nullable=False),
        sa.Column("source_product_id", sa.String(length=191), nullable=True),
        sa.Column("product_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
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
            ["collection_id"],
            ["imported_collections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_session_id"],
            ["marketplace_sync_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id",
            "external_item_id",
            name="uq_imported_items_collection_external_item",
        ),
    )


def downgrade() -> None:
    op.drop_table("imported_items")
    op.drop_table("product_offers")
    op.drop_table("marketplace_sync_sessions")
    op.drop_table("product_match_groups")
    op.drop_table("imported_collections")
    op.drop_table("store_sources")
    op.drop_table("audit_events")
    op.drop_table("notification_preferences")
    op.drop_table("idempotency_records")
    op.drop_table("stores")
    op.drop_table("user_regions")
