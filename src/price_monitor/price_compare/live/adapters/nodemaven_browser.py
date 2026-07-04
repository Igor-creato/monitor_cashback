from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any
from urllib.parse import quote

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    STORE_STATUS_OK,
    LiveSearchQuery,
    LiveStoreResult,
    antibot_warnings,
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


@dataclass(frozen=True, slots=True)
class BrowserPageSnapshot:
    status_code: int | None
    final_url: str
    content: str


BrowserFetcher = Callable[[str, str, int], BrowserPageSnapshot]


class NodeMavenBrowserSearchAdapter:
    def __init__(
        self,
        *,
        domain: str,
        search_url_template: str,
        browser_ws_url: str,
        parser: str,
        timeout_seconds: int = 120,
        fetcher: BrowserFetcher | None = None,
    ) -> None:
        self._domain = normalize_domain(domain)
        self._search_url_template = search_url_template
        self._browser_ws_url = browser_ws_url.strip()
        self._parser = parser
        self._timeout_ms = int(timeout_seconds * 1000)
        self._fetcher = fetcher or _fetch_page_over_cdp

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        if not self._browser_ws_url:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["nodemaven_browser_not_configured"],
                message="Провайдер поиска не настроен",
            )

        try:
            snapshot = self._fetcher(
                self._browser_ws_url, self._target_url(query), self._timeout_ms
            )
        except Exception:
            return _provider_failed(self._domain, "nodemaven_browser_request_failed")

        if _is_antibot_snapshot(snapshot):
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                items=[],
                warnings=antibot_warnings(snapshot.status_code),
                message="Магазин ограничил автоматический доступ",
            )
        if snapshot.status_code is not None and snapshot.status_code >= 400:
            return _provider_failed(self._domain, "nodemaven_browser_http_failed")
        if not snapshot.content:
            return _provider_failed(self._domain, "nodemaven_browser_empty_response")

        items = parse_items(self._parser, snapshot.content, self._domain, query.limit)
        if not items:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["nodemaven_browser_no_items"],
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


def _fetch_page_over_cdp(
    browser_ws_url: str, target_url: str, timeout_ms: int
) -> BrowserPageSnapshot:
    playwright_api: Any = import_module("playwright.sync_api")
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(browser_ws_url, timeout=timeout_ms)
        try:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _wait_for_network_idle(page, timeout_ms)
            return BrowserPageSnapshot(
                status_code=response.status if response is not None else None,
                final_url=str(page.url),
                content=str(page.content()),
            )
        finally:
            browser.close()


def _wait_for_network_idle(page: Any, timeout_ms: int) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15_000))
    except Exception:
        return


def _provider_failed(domain: str, warning: str) -> LiveStoreResult:
    return LiveStoreResult(
        store_domain=domain,
        status=STORE_STATUS_FAILED,
        items=[],
        warnings=[warning],
        message="Провайдер поиска не смог получить страницу магазина",
    )


def _is_antibot_snapshot(snapshot: BrowserPageSnapshot) -> bool:
    if snapshot.status_code in _BLOCKED_STATUSES:
        return True
    body = snapshot.content[:8192].lower()
    return any(marker in body for marker in _ANTIBOT_MARKERS)
