from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.monitoring import Store, StoreSource


@dataclass(frozen=True)
class StoreBrand:
    display_name: str
    logo_url: str | None


def get_store_brand_map(
    session: Session,
    source_codes: Iterable[str],
) -> dict[str, StoreBrand]:
    codes = {code.strip() for code in source_codes if code and code.strip()}
    if not codes:
        return {}

    brands: dict[str, StoreBrand] = {}
    sources = session.scalars(
        select(StoreSource)
        .options(selectinload(StoreSource.store))
        .where(StoreSource.source_code.in_(codes))
    ).all()
    for source in sources:
        brands[source.source_code] = StoreBrand(
            display_name=source.store.display_name,
            logo_url=source.store.logo_url,
        )

    stores = session.scalars(select(Store).where(Store.store_code.in_(codes))).all()
    for store in stores:
        brands.setdefault(
            store.store_code,
            StoreBrand(display_name=store.display_name, logo_url=store.logo_url),
        )

    return brands
