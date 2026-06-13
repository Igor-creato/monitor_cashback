"""add fetch attempts

Revision ID: 20260613_0009
Revises: 20260610_0008
Create Date: 2026-06-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260613_0009"
down_revision: str | None = "20260610_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fetch_attempts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("fetch_job_id", sa.BigInteger(), nullable=True),
        sa.Column("tracked_product_id", sa.BigInteger(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("strategy", sa.String(length=64), nullable=False),
        sa.Column("proxy_pool_id", sa.BigInteger(), nullable=True),
        sa.Column("proxy_endpoint_id", sa.BigInteger(), nullable=True),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=True),
        sa.Column("cost_estimated", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=True),
        sa.Column(
            "product_data_found",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "price_found",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "image_found",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["fetch_job_id"],
            ["fetch_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_product_id"],
            ["tracked_products.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proxy_pool_id"],
            ["proxy_pools.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["proxy_endpoint_id"],
            ["proxy_endpoints.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("fetch_attempts")
