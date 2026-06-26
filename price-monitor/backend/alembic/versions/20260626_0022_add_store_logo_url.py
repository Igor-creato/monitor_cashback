"""add store logo url

Revision ID: 20260626_0022
Revises: 20260625_0021
Create Date: 2026-06-26 00:22:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260626_0022"
down_revision = "20260625_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stores", sa.Column("logo_url", sa.String(length=2048), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stores", "logo_url")
