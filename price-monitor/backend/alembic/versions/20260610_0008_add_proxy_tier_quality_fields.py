"""add proxy tier and quality fields

Revision ID: 20260610_0008
Revises: 20260609_0007
Create Date: 2026-06-10 00:08:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_0008"
down_revision: str | None = "20260609_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proxy_pools",
        sa.Column(
            "tier",
            sa.String(length=32),
            nullable=False,
            server_default="standard",
        ),
    )
    op.add_column(
        "proxy_pools",
        sa.Column("cost_per_request", sa.Numeric(12, 8), nullable=True),
    )
    op.add_column(
        "proxy_pools",
        sa.Column("cost_per_gb", sa.Numeric(12, 8), nullable=True),
    )
    op.add_column(
        "proxy_pools",
        sa.Column("country_code", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "proxy_pools",
        sa.Column("region_code", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "proxy_pools",
        sa.Column(
            "sticky_session_supported",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "proxy_pools",
        sa.Column("max_cost_per_success", sa.Numeric(12, 8), nullable=True),
    )
    op.add_column(
        "proxy_pools",
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )
    op.add_column(
        "proxy_pools",
        sa.Column("source_affinity", sa.JSON(), nullable=True),
    )

    op.add_column(
        "proxy_endpoints",
        sa.Column("success_rate_1h", sa.Float(), nullable=True),
    )
    op.add_column(
        "proxy_endpoints",
        sa.Column("success_rate_24h", sa.Float(), nullable=True),
    )
    op.add_column(
        "proxy_endpoints",
        sa.Column("avg_response_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "proxy_endpoints",
        sa.Column(
            "ban_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "proxy_endpoints",
        sa.Column("last_403_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "proxy_endpoints",
        sa.Column("last_429_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "proxy_endpoints",
        sa.Column("last_captcha_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proxy_endpoints", "last_captcha_at")
    op.drop_column("proxy_endpoints", "last_429_at")
    op.drop_column("proxy_endpoints", "last_403_at")
    op.drop_column("proxy_endpoints", "ban_score")
    op.drop_column("proxy_endpoints", "avg_response_ms")
    op.drop_column("proxy_endpoints", "success_rate_24h")
    op.drop_column("proxy_endpoints", "success_rate_1h")

    op.drop_column("proxy_pools", "source_affinity")
    op.drop_column("proxy_pools", "priority")
    op.drop_column("proxy_pools", "max_cost_per_success")
    op.drop_column("proxy_pools", "sticky_session_supported")
    op.drop_column("proxy_pools", "region_code")
    op.drop_column("proxy_pools", "country_code")
    op.drop_column("proxy_pools", "cost_per_gb")
    op.drop_column("proxy_pools", "cost_per_request")
    op.drop_column("proxy_pools", "tier")
