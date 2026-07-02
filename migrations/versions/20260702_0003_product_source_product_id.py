"""product source product id

Revision ID: 20260702_0003
Revises: 20260630_0002
Create Date: 2026-07-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260702_0003"
down_revision: str | None = "20260630_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.add_column(sa.Column("source_product_id", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_products_source_product_id",
        "products",
        ["source_product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_products_source_product_id", table_name="products")
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("source_product_id")
