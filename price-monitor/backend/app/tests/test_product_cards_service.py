from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core import config
from app.models.monitoring import (
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.services.product_cards import build_product_card, build_product_card_list


def _product(**overrides) -> TrackedProduct:
    values = {
        "id": 123,
        "source": "ozon",
        "source_display_name": "Ozon",
        "external_product_id": "sku-123",
        "canonical_url": "https://ozon.example/product/123",
        "product_name": "Palit Видеокарта GeForce RTX 5070",
        "image_url": "https://saved.example/products/123.jpg",
        "last_price": Decimal("809.70"),
        "last_old_price": None,
        "currency": "USD",
        "last_availability": True,
        "last_checked_at": datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return TrackedProduct(**values)


def _subscription(product: TrackedProduct) -> UserProductSubscription:
    return UserProductSubscription(
        id=456,
        site_id="savelloclub.ru",
        external_user_id="wp:savelloclub.ru:123",
        tracked_product=product,
    )


def test_card_builds_title_image_source_and_price() -> None:
    product = _product()

    card = build_product_card(product, _subscription(product))

    assert card.tracked_product_id == 123
    assert card.subscription_id == 456
    assert card.title == "Palit Видеокарта GeForce RTX 5070"
    assert card.image_url == "https://saved.example/products/123.jpg"
    assert card.source == "ozon"
    assert card.source_display_name == "Ozon"
    assert card.canonical_url == "https://ozon.example/product/123"
    assert card.last_price == "809.70"
    assert card.last_old_price is None
    assert card.currency == "USD"
    assert card.availability is True
    assert card.last_checked_at == datetime(2026, 6, 8, 10, 0, tzinfo=UTC)


def test_image_object_key_uses_public_image_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config.settings,
        "product_image_public_base_url",
        "https://cdn.example.com/public/",
        raising=False,
    )
    product = _product(
        image_object_key="products/123 main.jpg",
        image_url="https://saved.example/fallback.jpg",
    )

    card = build_product_card(product)

    assert card.image_url == "https://cdn.example.com/public/products/123%20main.jpg"


def test_missing_image_object_key_uses_saved_image_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config.settings,
        "product_image_public_base_url",
        "https://cdn.example.com/public",
        raising=False,
    )
    product = _product(image_object_key=None)

    card = build_product_card(product)

    assert card.image_url == "https://saved.example/products/123.jpg"


def test_wildberries_card_recomputes_stale_saved_geobasket_image_url() -> None:
    product = _product(
        source="wildberries",
        source_display_name="Wildberries",
        external_product_id="904781586",
        canonical_url="https://www.wildberries.ru/catalog/904781586/detail.aspx",
        image_url=(
            "https://basket-37.wbbasket.ru/"
            "vol9047/part904781/904781586/images/big/1.webp"
        ),
    )

    card = build_product_card(product)

    assert card.image_url == (
        "https://sam-basket-cdn-04.geobasket.ru/"
        "vol9047/part904781/904781586/images/big/1.webp"
    )


def test_empty_title_falls_back_to_product_label() -> None:
    product = _product(product_name="   ")

    card = build_product_card(product)

    assert card.title == "Товар"


def test_missing_cashback_snapshot_returns_unknown() -> None:
    product = _product()

    card = build_product_card(product)

    assert card.cashback.cashback_status == "unknown"
    assert card.cashback.cashback_available is False
    assert card.cashback.display_policy == "cashback_unknown_requires_check"


def test_saved_cashback_snapshot_is_used_without_external_clients() -> None:
    product = _product()
    product.cashback = TrackedProductCashback(
        tracked_product=product,
        cashback_status="partner_exact",
        merchant_id="merchant-1",
        merchant_name="Merchant",
        network="admitad",
        offer_id="offer-1",
        user_cashback_exact_rate=Decimal("3.5"),
        expected_cashback_exact=Decimal("28.34"),
        effective_price=Decimal("781.36"),
        confidence="exact",
        display_policy="show_exact_rate",
        message="Точная ставка",
    )

    card = build_product_card(product)

    assert card.cashback.cashback_status == "partner_exact"
    assert card.cashback.cashback_available is True
    assert card.cashback.merchant_id == "merchant-1"
    assert card.cashback.user_cashback_exact_rate == "3.5"
    assert card.cashback.expected_cashback_exact == "28.34"
    assert card.cashback.effective_price == "781.36"


def test_card_list_accepts_products_and_subscriptions() -> None:
    product = _product(id=1)
    subscription = _subscription(product)

    cards = build_product_card_list([product, subscription])

    assert [card.tracked_product_id for card in cards] == [1, 1]
    assert [card.subscription_id for card in cards] == [None, 456]
