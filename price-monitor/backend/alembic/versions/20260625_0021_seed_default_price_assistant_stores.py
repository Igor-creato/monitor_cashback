"""seed default price assistant stores

Revision ID: 20260625_0021
Revises: 20260620_0020
Create Date: 2026-06-25 00:21:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260625_0021"
down_revision = "20260620_0020"
branch_labels = None
depends_on = None

DEFAULT_STORES = (
    {
        "store_code": "ozon",
        "display_name": "Ozon",
        "homepage_url": "https://www.ozon.ru/",
        "domains": ["ozon.ru", "www.ozon.ru"],
        "source_code": "ozon-default",
        "search_template": "https://www.ozon.ru/search/?text={query}",
    },
    {
        "store_code": "wildberries",
        "display_name": "Wildberries",
        "homepage_url": "https://www.wildberries.ru/",
        "domains": ["wildberries.ru", "www.wildberries.ru"],
        "source_code": "wildberries-default",
        "search_template": "https://www.wildberries.ru/catalog/0/search.aspx?search={query}",
    },
    {
        "store_code": "yandex_market",
        "display_name": "Яндекс Маркет",
        "homepage_url": "https://market.yandex.ru/",
        "domains": ["market.yandex.ru"],
        "source_code": "yandex_market-default",
        "search_template": "https://market.yandex.ru/search?text={query}",
    },
)


def upgrade() -> None:
    bind = op.get_bind()
    stores = sa.table(
        "stores",
        sa.column("id", sa.BigInteger()),
        sa.column("store_code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("homepage_url", sa.String()),
    )
    sources = sa.table(
        "store_sources",
        sa.column("id", sa.BigInteger()),
        sa.column("store_id", sa.BigInteger()),
        sa.column("source_code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("source_type", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("domains_json", sa.JSON()),
        sa.column("search_template", sa.String()),
        sa.column("region_support_json", sa.JSON()),
        sa.column("priority", sa.Integer()),
        sa.column("extraction_mode", sa.String()),
        sa.column("proxy_tier_policy", sa.String()),
        sa.column("min_fetch_interval_minutes", sa.Integer()),
        sa.column("matching_threshold", sa.Integer()),
        sa.column("metadata_json", sa.JSON()),
    )

    for item in DEFAULT_STORES:
        store_id = bind.scalar(
            sa.select(stores.c.id).where(stores.c.store_code == item["store_code"])
        )
        if store_id is None:
            store_id = _next_table_id(bind, stores)
            bind.execute(
                stores.insert().values(
                    id=store_id,
                    store_code=item["store_code"],
                    display_name=item["display_name"],
                    enabled=True,
                    homepage_url=item["homepage_url"],
                )
            )
        else:
            bind.execute(
                stores.update()
                .where(stores.c.id == store_id)
                .values(
                    display_name=item["display_name"],
                    enabled=True,
                    homepage_url=item["homepage_url"],
                )
            )

        source_id = bind.scalar(
            sa.select(sa.literal(1)).where(
                sa.exists().where(
                    sa.and_(
                        sources.c.store_id == store_id,
                        sources.c.source_code == item["source_code"],
                    )
                )
            )
        )
        source_values = {
            "display_name": item["display_name"],
            "source_type": "api",
            "enabled": True,
            "domains_json": item["domains"],
            "search_template": item["search_template"],
            "region_support_json": ["default"],
            "priority": 100,
            "extraction_mode": "hybrid",
            "proxy_tier_policy": "none",
            "min_fetch_interval_minutes": 60,
            "matching_threshold": 65,
            "metadata_json": {"matching": {"min_match_score": 65}},
        }
        if source_id is None:
            bind.execute(
                sources.insert().values(
                    id=_next_table_id(bind, sources),
                    store_id=store_id,
                    source_code=item["source_code"],
                    **source_values,
                )
            )
        else:
            bind.execute(
                sources.update()
                .where(
                    sa.and_(
                        sources.c.store_id == store_id,
                        sources.c.source_code == item["source_code"],
                    )
                )
                .values(**source_values)
            )


def _next_table_id(bind, table) -> int:
    value = bind.scalar(sa.select(sa.func.coalesce(sa.func.max(table.c.id), 0) + 1))
    return int(value or 1)


def downgrade() -> None:
    bind = op.get_bind()
    store_codes = [item["store_code"] for item in DEFAULT_STORES]
    source_codes = [item["source_code"] for item in DEFAULT_STORES]
    bind.execute(
        sa.text(
            "DELETE FROM store_sources WHERE source_code IN :source_codes"
        ).bindparams(sa.bindparam("source_codes", expanding=True)),
        {"source_codes": source_codes},
    )
    bind.execute(
        sa.text("DELETE FROM stores WHERE store_code IN :store_codes").bindparams(
            sa.bindparam("store_codes", expanding=True)
        ),
        {"store_codes": store_codes},
    )
