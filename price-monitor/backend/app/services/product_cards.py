from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from urllib.parse import quote

from app.core.config import settings
from app.models.monitoring import (
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.schemas.product_cards import (
    ProductCardCashbackResponse,
    ProductCardResponse,
)
from app.services.wildberries_media import wildberries_image_url


def build_product_card(
    tracked_product: TrackedProduct,
    subscription: UserProductSubscription | None = None,
) -> ProductCardResponse:
    return ProductCardResponse(
        tracked_product_id=tracked_product.id,
        subscription_id=subscription.id if subscription is not None else None,
        title=_title(tracked_product.product_name),
        image_url=_image_url(tracked_product),
        source=tracked_product.source,
        source_display_name=tracked_product.source_display_name,
        canonical_url=tracked_product.canonical_url,
        last_price=_format_money(tracked_product.last_price),
        last_old_price=_format_money(tracked_product.last_old_price),
        currency=tracked_product.currency,
        availability=tracked_product.last_availability,
        last_checked_at=tracked_product.last_checked_at,
        cashback=_cashback(tracked_product.cashback),
    )


def build_product_card_list(
    items: Iterable[TrackedProduct | UserProductSubscription],
) -> list[ProductCardResponse]:
    cards: list[ProductCardResponse] = []
    for item in items:
        if isinstance(item, UserProductSubscription):
            cards.append(build_product_card(item.tracked_product, item))
        else:
            cards.append(build_product_card(item))
    return cards


def _title(product_name: str | None) -> str:
    title = (product_name or "").strip()
    return title or "Товар"


def _image_url(tracked_product: TrackedProduct) -> str | None:
    object_key = (tracked_product.image_object_key or "").strip().lstrip("/")
    base_url = settings.product_image_public_base_url.strip().rstrip("/")
    if object_key and base_url:
        return f"{base_url}/{quote(object_key, safe='/')}"
    if tracked_product.source == "wildberries":
        external_image_url = _wildberries_external_image_url(tracked_product)
        if external_image_url is not None:
            return external_image_url
    return tracked_product.image_url


def _wildberries_external_image_url(
    tracked_product: TrackedProduct,
) -> str | None:
    try:
        product_id = int(tracked_product.external_product_id)
    except (TypeError, ValueError):
        return None
    if product_id <= 0:
        return None
    return wildberries_image_url(product_id)


def _cashback(
    snapshot: TrackedProductCashback | None,
) -> ProductCardCashbackResponse:
    if snapshot is None:
        return ProductCardCashbackResponse(
            cashback_status="unknown",
            cashback_available=False,
            display_policy="cashback_unknown_requires_check",
        )

    return ProductCardCashbackResponse(
        cashback_status=snapshot.cashback_status,
        cashback_available=snapshot.cashback_status
        not in {"no_partner", "partner_unknown_product"},
        merchant_id=snapshot.merchant_id,
        merchant_name=snapshot.merchant_name,
        network=snapshot.network,
        offer_id=snapshot.offer_id,
        user_cashback_exact_rate=_format_rate(snapshot.user_cashback_exact_rate),
        user_cashback_min_rate=_format_rate(snapshot.user_cashback_min_rate),
        user_cashback_max_rate=_format_rate(snapshot.user_cashback_max_rate),
        expected_cashback_exact=_format_money(snapshot.expected_cashback_exact),
        expected_cashback_min=_format_money(snapshot.expected_cashback_min),
        expected_cashback_max=_format_money(snapshot.expected_cashback_max),
        effective_price=_format_money(snapshot.effective_price),
        effective_price_conservative=_format_money(
            snapshot.effective_price_conservative
        ),
        confidence=snapshot.confidence,
        display_policy=snapshot.display_policy,
        message=snapshot.message,
    )


def _format_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _format_rate(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")
