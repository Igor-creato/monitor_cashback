"""add source fetch profiles

Revision ID: 20260609_0007
Revises: 20260608_0006
Create Date: 2026-06-09 00:07:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260609_0007"
down_revision: str | None = "20260608_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_fetch_profiles",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("difficulty_class", sa.String(length=16), nullable=False),
        sa.Column("preferred_transport", sa.String(length=32), nullable=False),
        sa.Column("fallback_transports", sa.JSON(), nullable=False),
        sa.Column("proxy_tier_policy", sa.String(length=32), nullable=False),
        sa.Column("browser_required", sa.Boolean(), nullable=False),
        sa.Column("extraction_mode", sa.String(length=16), nullable=False),
        sa.Column("image_policy", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint(
            "source_code",
            name="uq_source_fetch_profiles_source_code",
        ),
    )


def downgrade() -> None:
    op.drop_table("source_fetch_profiles")
