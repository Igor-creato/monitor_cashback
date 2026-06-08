"""add product card fields

Revision ID: 20260608_0006
Revises: 20260608_0005
Create Date: 2026-06-08 00:06:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260608_0006"
down_revision: str | None = "20260608_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tracked_products",
        sa.Column("image_object_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "tracked_products",
        sa.Column("source_display_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tracked_products", "source_display_name")
    op.drop_column("tracked_products", "image_object_key")
