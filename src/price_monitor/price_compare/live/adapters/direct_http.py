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
from price_monitor.price_compare.schemas import normalize_domain

_BLOCKED_STATUSES = {401, 403, 429}
_ANTIBOT_MARKERS = (
    "captcha",
    "robot",
    "servicepipe",
    "verify",
    "подтвердите",
    "доступ ограничен",
)


class DirectHttpSearchAdapter:
    def __init__(
        self,
        *,
        domain: str,
        search_url_template: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._domain = normalize_domain(domain)
        self._search_url_template = search_url_template
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(5.0),
            headers={"User-Agent": "MonitorCashbackLiveSearch/0.1 (+price comparison)"},
        )

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        url = self._search_url_template.format(
            query=quote(query.query),
            city=quote(query.city),
        )
        try:
            response = self._client.get(url)
        except httpx.HTTPError:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["live_http_failed"],
                message="Магазин временно недоступен",
            )

        if _is_antibot_response(response):
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                items=[],
                warnings=["blocked_by_antibot"],
                message="Магазин ограничил автоматический доступ",
            )

        return LiveStoreResult(
            store_domain=self._domain,
            status=STORE_STATUS_OK,
            items=[],
            warnings=["direct_http_parser_not_configured"],
        )


def _is_antibot_response(response: httpx.Response) -> bool:
    if response.status_code in _BLOCKED_STATUSES:
        return True
    body = response.text[:4096].lower()
    return any(marker in body for marker in _ANTIBOT_MARKERS)
