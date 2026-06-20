"""add incoming hmac replay records

Revision ID: 20260620_0020
Revises: 20260620_0019
Create Date: 2026-06-20 00:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260620_0020"
down_revision: str | None = "20260620_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incoming_hmac_replay_records",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("timestamp", sa.Integer(), nullable=False),
        sa.Column("signature_hash", sa.String(length=64), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id",
            "method",
            "path",
            "timestamp",
            "signature_hash",
            "body_hash",
            name="uq_incoming_hmac_replay_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("incoming_hmac_replay_records")
