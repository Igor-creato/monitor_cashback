from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import urljoin

from price_monitor.price_compare.live.adapters.base import LiveSearchItem

_JSON_LD_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_CITILINK_GRAPHQL_PATTERN = re.compile(
    r"<script[^>]+data-monitor-cashback-live-json=[\"']citilink_graphql[\"'][^>]*>"
    r"(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def parse_items(parser: str, content: str, domain: str, limit: int) -> list[LiveSearchItem]:
    if parser == "citilink_search_v1":
        return _parse_citilink_products(content, domain, limit)
    return []


def _parse_citilink_products(content: str, domain: str, limit: int) -> list[LiveSearchItem]:
    items = _parse_json_ld_products(content, domain, limit)
    seen_urls = {item.url for item in items}
    for item in _parse_citilink_graphql_products(content, domain, limit):
        if item.url in seen_urls:
            continue
        items.append(item)
        seen_urls.add(item.url)
        if len(items) >= limit:
            break
    return items


def _parse_json_ld_products(content: str, domain: str, limit: int) -> list[LiveSearchItem]:
    items: list[LiveSearchItem] = []
    base_url = f"https://{domain}/"
    for script in _JSON_LD_PATTERN.findall(content):
        decoded = unescape(script).strip()
        if not decoded:
            continue
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        for product in _iter_products(data):
            item = _product_to_item(product, domain=domain, base_url=base_url)
            if item is not None:
                items.append(item)
                if len(items) >= limit:
                    return items
    return items


def _parse_citilink_graphql_products(content: str, domain: str, limit: int) -> list[LiveSearchItem]:
    items: list[LiveSearchItem] = []
    for script in _CITILINK_GRAPHQL_PATTERN.findall(content):
        decoded = unescape(script).strip().replace("<\\/", "</")
        if not decoded:
            continue
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        for product in _iter_citilink_graphql_products(data):
            item = _citilink_graphql_product_to_item(product, domain=domain)
            if item is not None:
                items.append(item)
                if len(items) >= limit:
                    return items
    return items


def _iter_citilink_graphql_products(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    data = value.get("data")
    if not isinstance(data, dict):
        return []
    search_filter = data.get("fullSearchFilter")
    if not isinstance(search_filter, dict):
        return []
    record = search_filter.get("record")
    if not isinstance(record, dict):
        return []
    products = record.get("products")
    if not isinstance(products, list):
        return []
    return [product for product in products if isinstance(product, dict)]


def _citilink_graphql_product_to_item(
    product: dict[str, Any], *, domain: str
) -> LiveSearchItem | None:
    external_id = _string(product.get("id"))
    title = _string(product.get("name") or product.get("shortName"))
    slug = _string(product.get("slug"))
    if not external_id or not title or not slug:
        return None

    return LiveSearchItem(
        title=title,
        price=_citilink_price(product.get("price")),
        url=f"https://www.{domain}/product/{slug}-{external_id}/",
        availability="in_stock" if product.get("isAvailable") is True else "out_of_stock",
        store_domain=domain,
        store_name=domain,
        currency="RUB",
        image_url=_citilink_image_url(product.get("images")),
        category=_mapping_name(product.get("category")),
        brand=_mapping_name(product.get("brand")),
        external_id=external_id,
    )


def _citilink_price(value: object) -> Decimal | None:
    if not isinstance(value, dict):
        return None
    return _decimal_or_none(
        value.get("current") or value.get("value") or value.get("price") or value.get("amount")
    )


def _citilink_image_url(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    image_groups = value.get("citilink")
    if not isinstance(image_groups, list):
        return None
    candidates: dict[str, str] = {}
    fallback = ""
    for image_group in image_groups:
        if not isinstance(image_group, dict):
            continue
        sources = image_group.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = _string(source.get("url"))
            if not url:
                continue
            fallback = fallback or url
            size = _string(source.get("size")).upper()
            if size:
                candidates[size] = url
    for size in ("MD", "ML", "XL", "SM"):
        if size in candidates:
            return candidates[size]
    return fallback or None


def _mapping_name(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    name = _string(value.get("name"))
    return name or None


def _iter_products(value: object) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            products.extend(_iter_products(item))
        return products
    if not isinstance(value, dict):
        return products

    type_value = value.get("@type")
    types = type_value if isinstance(type_value, list) else [type_value]
    if any(str(item).lower() == "product" for item in types):
        products.append(value)

    for key in ("@graph", "itemListElement", "item", "offers"):
        nested = value.get(key)
        if nested is not None:
            products.extend(_iter_products(nested))
    return products


def _product_to_item(
    product: dict[str, Any], *, domain: str, base_url: str
) -> LiveSearchItem | None:
    title = _string(product.get("name"))
    raw_url = _string(product.get("url"))
    if not title or not raw_url:
        return None

    offer = _first_mapping(product.get("offers"))
    price = _decimal_or_none(offer.get("price") or offer.get("lowPrice"))
    return LiveSearchItem(
        title=title,
        price=price,
        url=urljoin(base_url, raw_url),
        availability=_availability(_string(offer.get("availability"))),
        store_domain=domain,
        store_name=domain,
        currency=_string(offer.get("priceCurrency")) or "RUB",
        image_url=_image_url(product.get("image"), base_url),
        category=_string(product.get("category")) or None,
        brand=_brand(product.get("brand")),
        external_id=_string(product.get("sku")) or None,
    )


def _first_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _availability(value: str) -> str:
    normalized = value.lower()
    if "instock" in normalized or "in_stock" in normalized:
        return "in_stock"
    if "outofstock" in normalized or "out_of_stock" in normalized:
        return "out_of_stock"
    return "unknown"


def _image_url(value: object, base_url: str) -> str | None:
    if isinstance(value, str) and value.strip():
        return urljoin(base_url, value.strip())
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return urljoin(base_url, item.strip())
    return None


def _brand(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None
