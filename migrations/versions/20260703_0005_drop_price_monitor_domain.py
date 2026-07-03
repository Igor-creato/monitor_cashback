"""drop price monitor domain tables

Revision ID: 20260703_0005
Revises: 20260702_0004
Create Date: 2026-07-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260703_0005"
down_revision: str | None = "20260702_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in (
        "alert_events",
        "price_points",
        "fetch_attempts",
        "watchlist_items",
        "fetch_jobs",
        "proxy_endpoints",
        "proxy_pools",
        "monitor_settings",
        "monitored_sources",
        "source_statuses",
        "idempotency_records",
        "inbox_messages",
        "outbox_events",
        "products",
    ):
        op.drop_table(table_name)


def downgrade() -> None:
    pass
