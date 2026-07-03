from decimal import Decimal

from price_monitor.price_compare.search import OfferSearchRow, sort_offers_by_price


def test_sort_offers_by_price_keeps_unknown_availability_after_known_items() -> None:
    offers = [
        OfferSearchRow(
            id="b",
            title="B",
            store_domain="shop-b.test",
            price=Decimal("120.00"),
            availability="unknown",
        ),
        OfferSearchRow(
            id="a",
            title="A",
            store_domain="shop-a.test",
            price=Decimal("100.00"),
            availability="in_stock",
        ),
        OfferSearchRow(
            id="c",
            title="C",
            store_domain="shop-c.test",
            price=Decimal("90.00"),
            availability="out_of_stock",
        ),
    ]

    sorted_ids = [offer.id for offer in sort_offers_by_price(offers)]

    assert sorted_ids == ["a", "b", "c"]


def test_sort_offers_by_price_uses_price_inside_same_availability_group() -> None:
    offers = [
        OfferSearchRow(
            id="expensive",
            title="Expensive",
            store_domain="shop-b.test",
            price=Decimal("120.00"),
            availability="in_stock",
        ),
        OfferSearchRow(
            id="cheap",
            title="Cheap",
            store_domain="shop-a.test",
            price=Decimal("100.00"),
            availability="in_stock",
        ),
    ]

    sorted_ids = [offer.id for offer in sort_offers_by_price(offers)]

    assert sorted_ids == ["cheap", "expensive"]
