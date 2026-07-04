from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    STORE_STATUS_OK,
    LiveSearchItem,
    LiveSearchQuery,
    LiveStoreResult,
)
from price_monitor.price_compare.schemas import normalize_domain

_BLOCKED_STATUSES = {401, 403, 429}
_ANTIBOT_MARKERS = (
    "captcha",
    "robot check",
    "servicepipe",
    "qrator",
    "подтвердите",
    "доступ ограничен",
)
_JSON_LD_PATTERN = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


class DecodoWebSearchAdapter:
    def __init__(
        self,
        *,
        domain: str,
        search_url_template: str,
        api_url: str,
        auth_token: str,
        parser: str,
        headless: str = "html",
        proxy_pool: str = "premium",
        device_type: str = "desktop",
        geo: str = "",
        locale: str = "",
        timeout_seconds: int = 150,
        client: httpx.Client | None = None,
    ) -> None:
        self._domain = normalize_domain(domain)
        self._search_url_template = search_url_template
        self._api_url = api_url.strip()
        self._auth_token = auth_token.strip()
        self._parser = parser
        self._headless = headless.strip()
        self._proxy_pool = proxy_pool.strip()
        self._device_type = device_type.strip()
        self._geo = geo.strip()
        self._locale = locale.strip()
        self._client = client or httpx.Client(timeout=httpx.Timeout(float(timeout_seconds)))

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        if not self._api_url or not self._auth_token:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["decodo_not_configured"],
                message="Провайдер поиска не настроен",
            )

        try:
            response = self._client.post(
                self._api_url,
                json=self._payload(query),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {self._auth_token}",
                },
            )
        except httpx.HTTPError:
            return _provider_failed(self._domain, "decodo_request_failed")

        if response.status_code in {401, 403}:
            return _provider_failed(self._domain, "decodo_auth_failed")
        if response.status_code == 429:
            return _provider_failed(self._domain, "decodo_rate_limited")
        if response.status_code >= 400:
            return _provider_failed(self._domain, "decodo_http_failed")

        try:
            payload = response.json()
        except ValueError:
            return _provider_failed(self._domain, "decodo_invalid_json")

        content, target_status = _extract_content(payload)
        if not content:
            return _provider_failed(self._domain, "decodo_scrape_failed")
        if target_status in _BLOCKED_STATUSES or _has_antibot_marker(content):
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                items=[],
                warnings=["blocked_by_antibot"],
                message="Магазин ограничил автоматический доступ",
            )

        items = _parse_items(self._parser, content, self._domain, query.limit)
        if not items:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["decodo_no_items"],
                message="Провайдер получил страницу, но товары не распознаны",
            )

        return LiveStoreResult(
            store_domain=self._domain,
            status=STORE_STATUS_OK,
            items=items,
            warnings=[],
        )

    def _payload(self, query: LiveSearchQuery) -> dict[str, object]:
        target_url = self._search_url_template.format(
            query=quote(query.query, safe=""),
            city=quote(query.city, safe=""),
        )
        payload: dict[str, object] = {"url": target_url}
        optional_values = {
            "headless": self._headless,
            "proxy_pool": self._proxy_pool,
            "device_type": self._device_type,
            "geo": self._geo,
            "locale": self._locale,
        }
        for key, value in optional_values.items():
            if value:
                payload[key] = value
        return payload


def _provider_failed(domain: str, warning: str) -> LiveStoreResult:
    return LiveStoreResult(
        store_domain=domain,
        status=STORE_STATUS_FAILED,
        items=[],
        warnings=[warning],
        message="Провайдер поиска не смог получить страницу магазина",
    )


def _extract_content(payload: object) -> tuple[str, int | None]:
    if not isinstance(payload, dict):
        return "", None
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return "", None
    first = results[0]
    if not isinstance(first, dict):
        return "", None
    content = first.get("content")
    status_code = first.get("status_code")
    return (
        content if isinstance(content, str) else "",
        status_code if isinstance(status_code, int) else None,
    )


def _has_antibot_marker(content: str) -> bool:
    lower = content[:8192].lower()
    return any(marker in lower for marker in _ANTIBOT_MARKERS)


def _parse_items(parser: str, content: str, domain: str, limit: int) -> list[LiveSearchItem]:
    if parser == "citilink_search_v1":
        return _parse_json_ld_products(content, domain, limit)
    return []


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
