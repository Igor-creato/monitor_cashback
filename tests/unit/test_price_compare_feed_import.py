from decimal import Decimal

from price_monitor.price_compare.feed import normalize_feed_item


def test_normalize_feed_item_maps_required_offer_fields() -> None:
    offer = normalize_feed_item(
        {
            "external_id": "sku-1",
            "title": " iPhone 15 128 ",
            "price": "79990.50",
            "currency": "rub",
            "url": "https://example-shop.ru/product/sku-1",
            "availability": "available",
            "image_url": "https://example-shop.ru/product/sku-1.jpg",
            "category": "Смартфоны",
            "brand": "Apple",
        },
        source="custom",
        store_domain="example-shop.ru",
    )

    assert offer.external_id == "sku-1"
    assert offer.title == "iPhone 15 128"
    assert offer.price == Decimal("79990.50")
    assert offer.currency == "RUB"
    assert offer.availability == "in_stock"
    assert offer.store_domain == "example-shop.ru"
    assert offer.category == "Смартфоны"
    assert offer.brand == "Apple"


def test_normalize_feed_item_marks_cpa_campaign_source_as_not_full_catalog() -> None:
    offer = normalize_feed_item(
        {
            "external_id": "campaign-1",
            "title": "Ozon campaign",
            "price": "",
            "url": "https://ozon.ru",
        },
        source="admitad",
        store_domain="ozon.ru",
    )

    assert offer.status == "FEED_NOT_COVERING_FULL_CATALOG"
    assert offer.price is None
