"""service foundation

Revision ID: 20260629_0001
Revises:
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column("canonical_url_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_domain", "canonical_url_hash", name="uq_products_source_url_hash"
        ),
    )
    op.create_index("ix_products_source_domain", "products", ["source_domain"])

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_url_hash", sa.String(length=64), nullable=False),
        sa.Column("target_price_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "canonical_url_hash", name="uq_watchlist_user_url_hash"),
    )
    op.create_index("ix_watchlist_items_user_id", "watchlist_items", ["user_id"])
    op.create_index("ix_watchlist_items_product_id", "watchlist_items", ["product_id"])
    op.create_index(
        "ix_watchlist_items_canonical_url_hash", "watchlist_items", ["canonical_url_hash"]
    )

    op.create_table(
        "price_points",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id", "source_domain", "observed_at", name="uq_price_points_sample"
        ),
    )
    op.create_index("ix_price_points_product_id", "price_points", ["product_id"])

    op.create_table(
        "source_statuses",
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source_domain"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=128), nullable=False),
        sa.Column("logical_key", sa.String(length=255), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("logical_key", name="uq_outbox_events_logical_key"),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_status", "outbox_events", ["status"])

    op.create_table(
        "inbox_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("consumer", sa.String(length=128), nullable=False),
        sa.Column("logical_key", sa.String(length=255), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "consumer", name="uq_inbox_message_consumer"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("route", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "route", name="uq_idempotency_key_route"),
    )

    op.create_table(
        "fetch_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("logical_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("logical_key", name="uq_fetch_jobs_logical_key"),
    )
    op.create_index("ix_fetch_jobs_product_id", "fetch_jobs", ["product_id"])
    op.create_index("ix_fetch_jobs_status", "fetch_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_fetch_jobs_status", table_name="fetch_jobs")
    op.drop_index("ix_fetch_jobs_product_id", table_name="fetch_jobs")
    op.drop_table("fetch_jobs")
    op.drop_table("idempotency_records")
    op.drop_table("inbox_messages")
    op.drop_index("ix_outbox_events_status", table_name="outbox_events")
    op.drop_index("ix_outbox_events_aggregate_id", table_name="outbox_events")
    op.drop_index("ix_outbox_events_event_type", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("source_statuses")
    op.drop_index("ix_price_points_product_id", table_name="price_points")
    op.drop_table("price_points")
    op.drop_index("ix_watchlist_items_canonical_url_hash", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_product_id", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_user_id", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_index("ix_products_source_domain", table_name="products")
    op.drop_table("products")
