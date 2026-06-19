"""add region model

Revision ID: 20260619_0017
Revises: 20260619_0016
Create Date: 2026-06-19 00:17:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260619_0017"
down_revision: str | None = "20260619_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "marketplace_connections",
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
    )
    op.add_column(
        "user_product_subscriptions",
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
    )
    op.add_column(
        "price_history",
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
    )
    op.add_column(
        "product_offers",
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
    )
    op.add_column(
        "imported_collections",
        sa.Column(
            "region_code",
            sa.String(length=64),
            server_default="default",
            nullable=False,
        ),
    )

    _backfill_region_codes()

    with op.batch_alter_table("marketplace_connections") as batch_op:
        batch_op.drop_constraint(
            "uq_marketplace_connections_identity",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_marketplace_connections_identity",
            ["site_id", "external_user_id", "marketplace", "region_code"],
        )

    with op.batch_alter_table("imported_collections") as batch_op:
        batch_op.drop_constraint(
            "uq_imported_collections_owner_source_type",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_imported_collections_owner_source_type",
            ["site_id", "external_user_id", "source", "collection_type", "region_code"],
        )

    with op.batch_alter_table("product_offers") as batch_op:
        batch_op.drop_constraint("uq_product_offers_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_product_offers_identity",
            ["match_group_id", "store_id", "external_product_id", "region_code"],
        )


def downgrade() -> None:
    with op.batch_alter_table("product_offers") as batch_op:
        batch_op.drop_constraint("uq_product_offers_identity", type_="unique")
        batch_op.create_unique_constraint(
            "uq_product_offers_identity",
            ["match_group_id", "store_id", "external_product_id"],
        )

    with op.batch_alter_table("imported_collections") as batch_op:
        batch_op.drop_constraint(
            "uq_imported_collections_owner_source_type",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_imported_collections_owner_source_type",
            ["site_id", "external_user_id", "source", "collection_type"],
        )

    with op.batch_alter_table("marketplace_connections") as batch_op:
        batch_op.drop_constraint(
            "uq_marketplace_connections_identity",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_marketplace_connections_identity",
            ["site_id", "external_user_id", "marketplace"],
        )

    op.drop_column("imported_collections", "region_code")
    op.drop_column("product_offers", "region_code")
    op.drop_column("price_history", "region_code")
    op.drop_column("user_product_subscriptions", "region_code")
    op.drop_column("marketplace_connections", "region_code")


def _backfill_region_codes() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                """
                UPDATE user_product_subscriptions
                SET region_code = COALESCE(
                    (
                        SELECT tracked_products.region_code
                        FROM tracked_products
                        WHERE tracked_products.id =
                            user_product_subscriptions.tracked_product_id
                    ),
                    'default'
                )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE price_history
                SET region_code = COALESCE(
                    (
                        SELECT tracked_products.region_code
                        FROM tracked_products
                        WHERE tracked_products.id = price_history.tracked_product_id
                    ),
                    'default'
                )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE product_offers
                SET region_code = COALESCE(
                    (
                        SELECT tracked_products.region_code
                        FROM tracked_products
                        JOIN product_match_groups
                            ON product_match_groups.tracked_product_id =
                                tracked_products.id
                        WHERE product_match_groups.id =
                            product_offers.match_group_id
                    ),
                    'default'
                )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE imported_collections
                SET region_code = COALESCE(
                    (
                        SELECT marketplace_connections.region_code
                        FROM marketplace_connections
                        WHERE marketplace_connections.id =
                            imported_collections.connection_id
                    ),
                    'default'
                )
                """
            )
        )
        return

    op.execute(
        sa.text(
            """
            UPDATE user_product_subscriptions AS subscriptions
            JOIN tracked_products AS products
                ON products.id = subscriptions.tracked_product_id
            SET subscriptions.region_code = products.region_code
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE price_history AS history
            JOIN tracked_products AS products
                ON products.id = history.tracked_product_id
            SET history.region_code = products.region_code
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE product_offers AS offers
            JOIN product_match_groups AS groups
                ON groups.id = offers.match_group_id
            JOIN tracked_products AS products
                ON products.id = groups.tracked_product_id
            SET offers.region_code = products.region_code
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE imported_collections AS collections
            JOIN marketplace_connections AS connections
                ON connections.id = collections.connection_id
            SET collections.region_code = connections.region_code
            """
        )
    )
