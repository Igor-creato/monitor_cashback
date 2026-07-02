from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from price_monitor.domains.fetching.ports import FetchedProductData


class _JsonLdScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._buffer: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return

        attr_map = {name.lower(): value for name, value in attrs}
        script_type = (attr_map.get("type") or "").lower()
        if script_type == "application/ld+json":
            self._capture = True
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._capture:
            return

        self.scripts.append("".join(self._buffer))
        self._capture = False
        self._buffer = []


class _MetaTagParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return

        attr_map = {
            name.lower(): value.strip()
            for name, value in attrs
            if value is not None and value.strip()
        }
        key = attr_map.get("property") or attr_map.get("name")
        content = attr_map.get("content")
        if key is None or content is None:
            return

        self.values.setdefault(key.lower(), content)


def extract_product_data(html: str, *, fallback_currency: str) -> FetchedProductData | None:
    parser = _JsonLdScriptParser()
    parser.feed(html)

    for script_content in parser.scripts:
        for candidate in _iter_product_nodes(_load_json(script_content)):
            data = _build_product_data(candidate, fallback_currency=fallback_currency)
            if data is not None:
                return data
    return _extract_meta_product_data(html, fallback_currency=fallback_currency)


def detect_fetch_block_reason(html: str) -> str | None:
    normalized = html.lower()
    if "_____tmd_____/punish" in normalized and '"action":"captcha"' in normalized:
        return "captcha_detected"
    if "x5secdata" in normalized and '"action":"captcha"' in normalized:
        return "captcha_detected"
    return None


def _load_json(payload: str) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _iter_product_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return

        if _is_product_node(value):
            nodes.append(value)

        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                visit(item)

    visit(payload)
    return nodes


def _is_product_node(node: dict[str, Any]) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, str):
        return node_type == "Product"
    if isinstance(node_type, list):
        return "Product" in node_type
    return False


def _build_product_data(
    product_node: dict[str, Any], *, fallback_currency: str
) -> FetchedProductData | None:
    title = product_node.get("name")
    if not isinstance(title, str) or not title.strip():
        return None

    offers = product_node.get("offers")
    price_minor, currency = _extract_offer_data(offers, fallback_currency=fallback_currency)
    if price_minor is None or currency is None:
        return None

    return FetchedProductData(
        title=title.strip(),
        image_url=_extract_image_url(product_node.get("image")),
        price_minor=price_minor,
        currency=currency,
        rating_value=_extract_rating_value(product_node.get("aggregateRating")),
    )


def _extract_meta_product_data(html: str, *, fallback_currency: str) -> FetchedProductData | None:
    parser = _MetaTagParser()
    parser.feed(html)
    values = parser.values

    title = values.get("og:title") or values.get("twitter:title")
    if title is None or not title.strip():
        return None

    raw_price = (
        values.get("product:price:amount") or values.get("og:price:amount") or values.get("price")
    )
    price_minor = _to_minor_units(raw_price)
    if price_minor is None or price_minor <= 0:
        return None

    raw_currency = (
        values.get("product:price:currency") or values.get("og:price:currency") or fallback_currency
    )
    currency = raw_currency.strip() if raw_currency.strip() else fallback_currency

    return FetchedProductData(
        title=title.strip(),
        image_url=values.get("og:image") or values.get("twitter:image"),
        price_minor=price_minor,
        currency=currency.upper(),
        rating_value=None,
    )


def _extract_offer_data(offers: Any, *, fallback_currency: str) -> tuple[int | None, str | None]:
    offer_candidates = offers if isinstance(offers, list) else [offers]
    for offer in offer_candidates:
        if not isinstance(offer, dict):
            continue
        raw_price = offer.get("price", offer.get("lowPrice"))
        price_minor = _to_minor_units(raw_price)
        if price_minor is None or price_minor <= 0:
            continue
        raw_currency = offer.get("priceCurrency")
        currency = (
            raw_currency
            if isinstance(raw_currency, str) and raw_currency.strip()
            else fallback_currency
        )
        return price_minor, currency.upper()
    return None, None


def _extract_image_url(image_value: Any) -> str | None:
    if isinstance(image_value, str) and image_value.strip():
        return image_value.strip()
    if isinstance(image_value, list):
        for item in image_value:
            extracted = _extract_image_url(item)
            if extracted is not None:
                return extracted
        return None
    if isinstance(image_value, dict):
        for key in ("url", "contentUrl"):
            value = image_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_rating_value(aggregate_rating: Any) -> str | None:
    if not isinstance(aggregate_rating, dict):
        return None
    rating = aggregate_rating.get("ratingValue")
    if rating is None:
        return None
    if isinstance(rating, str):
        stripped = rating.strip()
        return stripped or None
    if isinstance(rating, (int, float, Decimal)):
        return str(rating)
    return None


def _to_minor_units(raw_price: Any) -> int | None:
    if isinstance(raw_price, str):
        normalized = raw_price.strip().replace(",", ".")
    elif isinstance(raw_price, (int, float, Decimal)):
        normalized = str(raw_price)
    else:
        return None

    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None

    minor = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)
