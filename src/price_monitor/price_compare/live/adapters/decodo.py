from __future__ import annotations

from urllib.parse import quote

import httpx

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    STORE_STATUS_OK,
    LiveSearchQuery,
    LiveStoreResult,
)
from price_monitor.price_compare.live.adapters.parsers import parse_items
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

        items = parse_items(self._parser, content, self._domain, query.limit)
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
