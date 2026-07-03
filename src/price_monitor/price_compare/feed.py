from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

CPA_CAMPAIGN_SOURCES = frozenset({"admitad", "advcake"})


@dataclass(frozen=True, slots=True)
class NormalizedOffer:
    source: str
    store_domain: str
    external_id: str
    title: str
    url: str
    price: Decimal | None
    currency: str
    availability: str
    image_url: str | None = None
    category: str | None = None
    brand: str | None = None
    status: str = "ok"


def normalize_feed_item(
    raw: Mapping[str, object], *, source: str, store_domain: str
) -> NormalizedOffer:
    normalized_source = source.strip().lower()
    title = _string_value(raw.get("title")).strip()
    url = _string_value(raw.get("url")).strip()
    external_id = _string_value(raw.get("external_id")).strip() or url

    if normalized_source in CPA_CAMPAIGN_SOURCES:
        return NormalizedOffer(
            source=normalized_source,
            store_domain=_normalize_domain(store_domain),
            external_id=external_id,
            title=title,
            url=url,
            price=None,
            currency=_normalize_currency(raw.get("currency")),
            availability="unknown",
            image_url=_optional_string(raw.get("image_url")),
            category=_optional_string(raw.get("category")),
            brand=_optional_string(raw.get("brand")),
            status="FEED_NOT_COVERING_FULL_CATALOG",
        )

    return NormalizedOffer(
        source=normalized_source,
        store_domain=_normalize_domain(store_domain),
        external_id=external_id,
        title=title,
        url=url,
        price=_normalize_price(raw.get("price")),
        currency=_normalize_currency(raw.get("currency")),
        availability=_normalize_availability(raw.get("availability")),
        image_url=_optional_string(raw.get("image_url")),
        category=_optional_string(raw.get("category")),
        brand=_optional_string(raw.get("brand")),
    )


def _string_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_string(value: object) -> str | None:
    normalized = _string_value(value).strip()
    return normalized or None


def _normalize_domain(value: str) -> str:
    return value.strip().lower().removeprefix("www.")


def _normalize_currency(value: object) -> str:
    currency = _string_value(value).strip().upper()
    return currency or "RUB"


def _normalize_price(value: object) -> Decimal | None:
    raw_price = _string_value(value).strip().replace(",", ".")
    if not raw_price:
        return None
    try:
        return Decimal(raw_price)
    except InvalidOperation:
        return None


def _normalize_availability(value: object) -> str:
    availability = _string_value(value).strip().lower()
    if availability in {"available", "in_stock", "instock", "yes", "true", "1"}:
        return "in_stock"
    if availability in {"unavailable", "out_of_stock", "outofstock", "no", "false", "0"}:
        return "out_of_stock"
    return "unknown"
