from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from price_monitor.db.base import Base
from price_monitor.price_compare.models import Offer, StoreSource
from price_monitor.price_compare.repository import OfferRepository


def test_repository_searches_active_store_offers_sorted_by_price() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            StoreSource(
                domain="ozon.ru",
                display_name="Ozon",
                active=True,
                source_type="custom",
                supports_region=False,
            )
        )
        session.add(
            StoreSource(
                domain="inactive.test",
                display_name="Inactive",
                active=False,
                source_type="custom",
                supports_region=False,
            )
        )
        session.add_all(
            [
                Offer(
                    source="custom",
                    store_domain="ozon.ru",
                    external_id="expensive",
                    title="iPhone 15 128 Black",
                    normalized_title="iphone 15 128 black",
                    url="https://ozon.ru/product/expensive",
                    price=Decimal("90000.00"),
                    currency="RUB",
                    availability="in_stock",
                    region_supported=False,
                ),
                Offer(
                    source="custom",
                    store_domain="ozon.ru",
                    external_id="cheap",
                    title="iPhone 15 128 Blue",
                    normalized_title="iphone 15 128 blue",
                    url="https://ozon.ru/product/cheap",
                    price=Decimal("80000.00"),
                    currency="RUB",
                    availability="in_stock",
                    region_supported=False,
                ),
                Offer(
                    source="custom",
                    store_domain="inactive.test",
                    external_id="hidden",
                    title="iPhone 15 128 Hidden",
                    normalized_title="iphone 15 128 hidden",
                    url="https://inactive.test/product/hidden",
                    price=Decimal("1.00"),
                    currency="RUB",
                    availability="in_stock",
                    region_supported=False,
                ),
            ]
        )
        session.commit()

        results = OfferRepository(session).search(
            query="iphone 15 128",
            city="Москва",
            stores=[],
            limit=10,
            offset=0,
        )

    assert [offer.external_id for offer in results.items] == ["cheap", "expensive"]
    assert results.total == 2
