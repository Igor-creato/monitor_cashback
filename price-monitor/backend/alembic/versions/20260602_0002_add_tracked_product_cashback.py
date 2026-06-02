"""add tracked product cashback snapshot

Revision ID: 20260602_0002
Revises: 20260601_0001
Create Date: 2026-06-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260602_0002"
down_revision: str | None = "20260601_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tracked_product_cashback",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("tracked_product_id", sa.BigInteger(), nullable=False),
        sa.Column("cashback_status", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=191), nullable=True),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("network", sa.String(length=64), nullable=True),
        sa.Column("offer_id", sa.String(length=191), nullable=True),
        sa.Column("rate_id", sa.String(length=191), nullable=True),
        sa.Column("commission_rate_type", sa.String(length=16), nullable=True),
        sa.Column("commission_exact", sa.Numeric(12, 4), nullable=True),
        sa.Column("commission_min", sa.Numeric(12, 4), nullable=True),
        sa.Column("commission_max", sa.Numeric(12, 4), nullable=True),
        sa.Column("user_share", sa.Numeric(12, 4), nullable=True),
        sa.Column("user_cashback_exact_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("user_cashback_min_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("user_cashback_max_rate", sa.Numeric(12, 4), nullable=True),
        sa.Column("expected_cashback_exact", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_cashback_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("expected_cashback_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("effective_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("effective_price_conservative", sa.Numeric(12, 2), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("display_policy", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("raw_response_json", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
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
            name="uq_tracked_product_cashback_tracked_product_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("tracked_product_cashback")
