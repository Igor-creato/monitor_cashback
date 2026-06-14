"""add metrics counters

Revision ID: 20260614_0012
Revises: 20260614_0011
Create Date: 2026-06-14 00:12:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260614_0012"
down_revision: str | None = "20260614_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHART_REQUESTS_METRIC = "price_monitor_chart_requests_total"


def upgrade() -> None:
    op.create_table(
        "metrics_counters",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("value", sa.BigInteger(), server_default="0", nullable=False),
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
        sa.UniqueConstraint("name", name="uq_metrics_counters_name"),
    )
    op.bulk_insert(
        sa.table(
            "metrics_counters",
            sa.column("id", sa.BigInteger()),
            sa.column("name", sa.String(length=191)),
            sa.column("value", sa.BigInteger()),
        ),
        [{"id": 1, "name": CHART_REQUESTS_METRIC, "value": 0}],
    )


def downgrade() -> None:
    op.drop_table("metrics_counters")
