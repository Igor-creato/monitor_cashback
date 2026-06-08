"""add source config and health events

Revision ID: 20260608_0004
Revises: 20260608_0003
Create Date: 2026-06-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260608_0004"
down_revision: str | None = "20260608_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_configs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("fetch_strategy", sa.String(length=64), nullable=False),
        sa.Column("min_fetch_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("max_failures_before_quarantine", sa.Integer(), nullable=False),
        sa.Column("browser_fallback_enabled", sa.Boolean(), nullable=False),
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
            name="uq_source_configs_source_code",
        ),
    )
    op.create_table(
        "source_health_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("source_health_events")
    op.drop_table("source_configs")
