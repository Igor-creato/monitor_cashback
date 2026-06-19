"""add marketplace next sync timestamp

Revision ID: 20260619_0016
Revises: 20260615_0015
Create Date: 2026-06-19 00:16:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260619_0016"
down_revision: str | None = "20260615_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_connections",
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("marketplace_connections", "next_sync_at")
