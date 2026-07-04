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

_BLOCKED_STATUSES = {401, 403, 407, 429}
_ANTIBOT_MARKERS = (
    "captcha",
    "robot check",
    "servicepipe",
    "qrator",
    "подтвердите",
    "доступ ограничен",
)


class NodeMavenProxySearchAdapter:
    def __init__(
        self,
        *,
        domain: str,
        search_url_template: str,
        proxy_url: str,
        parser: str,
        timeout_seconds: int = 60,
        verify_ssl: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self._domain = normalize_domain(domain)
        self._search_url_template = search_url_template
        self._proxy_url = proxy_url.strip()
        self._parser = parser
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(float(timeout_seconds)),
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6",
                "User-Agent": "MonitorCashbackLiveSearch/0.1 (+price comparison)",
            },
            proxy=self._proxy_url or None,
            verify=verify_ssl,
            follow_redirects=True,
        )

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        if not self._proxy_url:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["nodemaven_not_configured"],
                message="Провайдер поиска не настроен",
            )

        try:
            response = self._client.get(self._target_url(query))
        except httpx.HTTPError:
            return _provider_failed(self._domain, "nodemaven_request_failed")

        if _is_antibot_response(response):
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                items=[],
                warnings=["blocked_by_antibot"],
                message="Магазин ограничил автоматический доступ",
            )
        if response.status_code >= 400:
            return _provider_failed(self._domain, "nodemaven_http_failed")

        content = response.text
        if not content:
            return _provider_failed(self._domain, "nodemaven_empty_response")

        items = parse_items(self._parser, content, self._domain, query.limit)
        if not items:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["nodemaven_no_items"],
                message="Провайдер получил страницу, но товары не распознаны",
            )

        return LiveStoreResult(
            store_domain=self._domain,
            status=STORE_STATUS_OK,
            items=items,
            warnings=[],
        )

    def _target_url(self, query: LiveSearchQuery) -> str:
        return self._search_url_template.format(
            query=quote(query.query, safe=""),
            city=quote(query.city, safe=""),
        )


def build_proxy_url(
    *,
    proxy_url: str,
    host: str,
    port: int,
    username: str,
    password: str,
) -> str:
    if proxy_url.strip():
        return proxy_url.strip()
    if not host.strip() or not username.strip() or not password:
        return ""
    return (
        f"http://{quote(username.strip(), safe='')}:"
        f"{quote(password, safe='')}@{host.strip()}:{port}"
    )


def _provider_failed(domain: str, warning: str) -> LiveStoreResult:
    return LiveStoreResult(
        store_domain=domain,
        status=STORE_STATUS_FAILED,
        items=[],
        warnings=[warning],
        message="Провайдер поиска не смог получить страницу магазина",
    )


def _is_antibot_response(response: httpx.Response) -> bool:
    if response.status_code in _BLOCKED_STATUSES:
        return True
    body = response.text[:8192].lower()
    return any(marker in body for marker in _ANTIBOT_MARKERS)
