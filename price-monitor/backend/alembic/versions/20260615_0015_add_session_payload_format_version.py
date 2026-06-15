"""add session payload format version

Revision ID: 20260615_0015
Revises: 20260615_0014
Create Date: 2026-06-15 00:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0015"
down_revision: str | None = "20260615_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_session_secrets",
        sa.Column(
            "payload_format_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("marketplace_session_secrets", "payload_format_version")
