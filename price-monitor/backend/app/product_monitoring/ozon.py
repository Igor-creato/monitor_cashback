from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup

from app.fetchers.base import FetchError, PriceFetchResult

CAPTCHA_MARKERS = (
    "captcha",
    "login_required",
    "access denied",
    "доступ ограничен",
    "подтвердите, что вы не робот",
    "войдите",
)


def parse_ozon_public_page(
    html: str | bytes,
    *,
    fetched_at: datetime,
) -> PriceFetchResult:
    text = html.decode("utf-8", errors="ignore") if isinstance(html, bytes) else html
    if _looks_blocked(text):
        raise FetchError("captcha_detected")

    soup = BeautifulSoup(text, "html.parser")
    product_payload = _find_product_payload(soup)
    if product_payload is None:
        raise FetchError("parser_error", "ozon product payload is missing")

    name = _text_value(product_payload.get("name")) or _meta_content(soup, "og:title")
    image_url = _image_value(product_payload.get("image")) or _meta_content(
        soup,
        "og:image",
    )
    offer = _first_offer(product_payload.get("offers"))
    price_current = _money(_payload_value(offer, "price"))
    if price_current is None:
        raise FetchError("price_not_found")

    price_old = _old_price(offer, price_current)
    currency = _text_value(_payload_value(offer, "priceCurrency")) or "RUB"
    availability = _availability(_text_value(_payload_value(offer, "availability")))
    seller = _seller_name(_payload_value(offer, "seller"))

    return PriceFetchResult(
        product_name=name,
        price_current=price_current,
        price_old=price_old,
        currency=currency,
        availability=availability,
        seller_name=seller,
        image_url=image_url,
        fetched_at=fetched_at,
    )


def _looks_blocked(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in CAPTCHA_MARKERS)


def _find_product_payload(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        payload = _loads_json(script.string or script.get_text())
        for item in _walk_json(payload):
            if _is_product_payload(item):
                return item
    return None


def _loads_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _walk_json(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
        for value in payload.values():
            yield from _walk_json(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _walk_json(value)


def _is_product_payload(payload: dict[str, Any]) -> bool:
    payload_type = payload.get("@type")
    if isinstance(payload_type, list):
        return "Product" in payload_type
    return payload_type == "Product"


def _first_offer(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    return payload.get(key)


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _image_value(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            text = _text_value(item)
            if text:
                return text
        return None
    return _text_value(value)


def _meta_content(soup: BeautifulSoup, property_name: str) -> str | None:
    tag = soup.find("meta", attrs={"property": property_name})
    if tag is None:
        return None
    return _text_value(tag.get("content"))


def _money(value: Any) -> Decimal | None:
    text = _text_value(value)
    if text is None:
        return None
    normalized = re.sub(r"[^\d,.]", "", text).replace(",", ".")
    if not normalized:
        return None
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _old_price(offer: dict[str, Any], price_current: Decimal) -> Decimal | None:
    price_spec = offer.get("priceSpecification")
    specs = price_spec if isinstance(price_spec, list) else [price_spec]
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        candidate = _money(spec.get("price"))
        if candidate is not None and candidate > price_current:
            return candidate
    return None


def _availability(value: str | None) -> bool:
    if value is None:
        return True
    lowered = value.lower()
    return "outofstock" not in lowered and "soldout" not in lowered


def _seller_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text_value(value.get("name"))
    return _text_value(value)
