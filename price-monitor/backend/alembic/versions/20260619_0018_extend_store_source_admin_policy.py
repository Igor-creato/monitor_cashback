"""extend store source admin policy

Revision ID: 20260619_0018
Revises: 20260619_0017
Create Date: 2026-06-19 00:18:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260619_0018"
down_revision = "20260619_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("store_sources", sa.Column("domains_json", sa.JSON(), nullable=True))
    op.add_column(
        "store_sources",
        sa.Column("search_template", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "store_sources",
        sa.Column("region_support_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "store_sources",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
    )
    op.add_column(
        "store_sources",
        sa.Column(
            "extraction_mode",
            sa.String(length=16),
            nullable=False,
            server_default="json",
        ),
    )
    op.add_column(
        "store_sources",
        sa.Column(
            "proxy_tier_policy",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "store_sources",
        sa.Column(
            "min_fetch_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="60",
        ),
    )
    op.add_column(
        "store_sources",
        sa.Column(
            "matching_threshold",
            sa.Integer(),
            nullable=False,
            server_default="65",
        ),
    )
    op.add_column(
        "store_sources",
        sa.Column("cashback_merchant_mapping_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("store_sources", "cashback_merchant_mapping_json")
    op.drop_column("store_sources", "matching_threshold")
    op.drop_column("store_sources", "min_fetch_interval_minutes")
    op.drop_column("store_sources", "proxy_tier_policy")
    op.drop_column("store_sources", "extraction_mode")
    op.drop_column("store_sources", "priority")
    op.drop_column("store_sources", "region_support_json")
    op.drop_column("store_sources", "search_template")
    op.drop_column("store_sources", "domains_json")
