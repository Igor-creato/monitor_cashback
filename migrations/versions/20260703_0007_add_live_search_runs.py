"""add live search runs

Revision ID: 20260703_0007
Revises: 20260703_0006
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260703_0007"
down_revision: str | None = "20260703_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_compare_live_search_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=80), nullable=False),
        sa.Column("query", sa.String(length=255), nullable=False),
        sa.Column("city", sa.String(length=255), nullable=False),
        sa.Column("stores", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("progress_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_price_compare_live_search_runs_run_id"),
    )
    op.create_index(
        "ix_price_compare_live_search_runs_run_id",
        "price_compare_live_search_runs",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_price_compare_live_search_runs_run_id",
        table_name="price_compare_live_search_runs",
    )
    op.drop_table("price_compare_live_search_runs")
