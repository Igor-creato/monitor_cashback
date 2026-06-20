"""extend notification delivery contract

Revision ID: 20260620_0019
Revises: 20260619_0018
Create Date: 2026-06-20 00:19:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260620_0019"
down_revision: str | None = "20260619_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification_preferences") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cooldown_minutes",
                sa.Integer(),
                server_default="1440",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "drop_threshold_percent",
                sa.Numeric(precision=5, scale=2),
                server_default="5.00",
                nullable=False,
            )
        )

    with op.batch_alter_table("notification_events") as batch_op:
        batch_op.add_column(
            sa.Column("channel", sa.String(length=32), server_default="email")
        )
        batch_op.add_column(sa.Column("dedup_key", sa.String(length=191)))
        batch_op.add_column(sa.Column("connection_id", sa.BigInteger()))
        batch_op.add_column(
            sa.Column(
                "delivery_attempts",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("last_error_type", sa.String(length=64)))
        batch_op.alter_column(
            "subscription_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )
        batch_op.alter_column(
            "tracked_product_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("UPDATE notification_events SET dedup_key = 'legacy:' || id")
    else:
        op.execute("UPDATE notification_events SET dedup_key = CONCAT('legacy:', id)")

    with op.batch_alter_table("notification_events") as batch_op:
        batch_op.alter_column(
            "channel",
            existing_type=sa.String(length=32),
            nullable=False,
            server_default="email",
        )
        batch_op.alter_column(
            "dedup_key",
            existing_type=sa.String(length=191),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_notification_events_connection_id",
            "marketplace_connections",
            ["connection_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_notification_events_delivery_identity",
            ["site_id", "external_user_id", "event_type", "channel", "dedup_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_events") as batch_op:
        batch_op.drop_constraint(
            "uq_notification_events_delivery_identity",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_notification_events_connection_id",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "tracked_product_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch_op.alter_column(
            "subscription_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
        batch_op.drop_column("last_error_type")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("delivery_attempts")
        batch_op.drop_column("connection_id")
        batch_op.drop_column("dedup_key")
        batch_op.drop_column("channel")

    with op.batch_alter_table("notification_preferences") as batch_op:
        batch_op.drop_column("drop_threshold_percent")
        batch_op.drop_column("cooldown_minutes")
