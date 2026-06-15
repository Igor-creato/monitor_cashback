"""add marketplace session storage

Revision ID: 20260615_0013
Revises: 20260614_0012
Create Date: 2026-06-15 00:13:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260615_0013"
down_revision: str | None = "20260614_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "marketplace_session_sources",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("disabled_reason", sa.String(length=255), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
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
            "marketplace",
            name="uq_marketplace_session_sources_marketplace",
        ),
    )
    op.create_table(
        "marketplace_session_allowlist",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=191), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="0", nullable=False),
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
            "marketplace",
            "name",
            "kind",
            "scope",
            name="uq_marketplace_session_allowlist_identity",
        ),
    )
    op.create_table(
        "marketplace_connections",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="connecting",
            nullable=False,
        ),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("consent_version", sa.String(length=191), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconnect_reason", sa.String(length=64), nullable=True),
        sa.Column("kill_switch_blocked_at", sa.DateTime(timezone=True), nullable=True),
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
            "site_id",
            "external_user_id",
            "marketplace",
            name="uq_marketplace_connections_identity",
        ),
    )
    op.create_table(
        "marketplace_session_secrets",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("encrypted_cookie_bundle", sa.Text(), nullable=False),
        sa.Column("dek_ciphertext", sa.Text(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column("aad_json", sa.JSON(), nullable=False),
        sa.Column("key_version", sa.String(length=64), nullable=False),
        sa.Column(
            "encryption_alg",
            sa.String(length=32),
            server_default="AES-256-GCM",
            nullable=False,
        ),
        sa.Column("bundle_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["marketplace_connections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "marketplace_session_audit_events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("connection_id", sa.BigInteger(), nullable=True),
        sa.Column("site_id", sa.String(length=191), nullable=False),
        sa.Column("external_user_id", sa.String(length=191), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["marketplace_connections.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("marketplace_session_audit_events")
    op.drop_table("marketplace_session_secrets")
    op.drop_table("marketplace_connections")
    op.drop_table("marketplace_session_allowlist")
    op.drop_table("marketplace_session_sources")
