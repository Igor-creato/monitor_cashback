"""fetch lifecycle metadata

Revision ID: 20260702_0004
Revises: 20260702_0003
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0004"
down_revision: str | None = "20260702_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("fetch_jobs") as batch_op:
        batch_op.add_column(sa.Column("status_reason", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("fetch_attempts") as batch_op:
        batch_op.add_column(sa.Column("provider_name", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("provider_request_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("provider_cost_minor", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("rendered", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("block_reason", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "challenge_detected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("parser_version", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("parser_confidence", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fetch_attempts") as batch_op:
        batch_op.drop_column("parser_confidence")
        batch_op.drop_column("parser_version")
        batch_op.drop_column("challenge_detected")
        batch_op.drop_column("block_reason")
        batch_op.drop_column("rendered")
        batch_op.drop_column("provider_cost_minor")
        batch_op.drop_column("provider_request_id")
        batch_op.drop_column("provider_name")

    with op.batch_alter_table("fetch_jobs") as batch_op:
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("finished_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("status_reason")
