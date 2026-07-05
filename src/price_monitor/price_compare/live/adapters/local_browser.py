from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any
from urllib.parse import quote, unquote, urlsplit

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
_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class LocalBrowserPageSnapshot:
    status_code: int | None
    final_url: str
    content: str


LocalBrowserFetcher = Callable[[str, int, str], LocalBrowserPageSnapshot]


class LocalBrowserSearchAdapter:
    def __init__(
        self,
        *,
        domain: str,
        search_url_template: str,
        parser: str,
        proxy_url: str,
        timeout_seconds: int = 120,
        fetcher: LocalBrowserFetcher | None = None,
    ) -> None:
        self._domain = normalize_domain(domain)
        self._search_url_template = search_url_template
        self._parser = parser
        self._proxy_url = proxy_url.strip()
        self._timeout_ms = int(timeout_seconds * 1000)
        self._fetcher = fetcher or _fetch_page_with_local_browser

    @property
    def proxy_url(self) -> str:
        return self._proxy_url

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        try:
            snapshot = self._fetcher(self._target_url(query), self._timeout_ms, self._proxy_url)
        except Exception:
            return _provider_failed(self._domain, "local_browser_request_failed")

        if _is_antibot_snapshot(snapshot):
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                items=[],
                warnings=antibot_warnings(snapshot.status_code, "local_browser"),
                message="Магазин ограничил автоматический доступ",
            )
        if snapshot.status_code is not None and snapshot.status_code >= 400:
            return _provider_failed(self._domain, "local_browser_http_failed")
        if not snapshot.content:
            return _provider_failed(self._domain, "local_browser_empty_response")

        items = parse_items(self._parser, snapshot.content, self._domain, query.limit)
        if not items:
            return LiveStoreResult(
                store_domain=self._domain,
                status=STORE_STATUS_FAILED,
                items=[],
                warnings=["local_browser_no_items"],
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


def _fetch_page_with_local_browser(
    target_url: str, timeout_ms: int, proxy_url: str
) -> LocalBrowserPageSnapshot:
    playwright_api: Any = import_module("playwright.sync_api")
    with playwright_api.sync_playwright() as playwright:
        launch_options: dict[str, object] = {"headless": True}
        if proxy_url:
            launch_options["proxy"] = _playwright_proxy_config(proxy_url)
        browser = playwright.chromium.launch(**launch_options)
        try:
            context = browser.new_context(**_browser_context_options())
            page = context.new_page()
            captured_json_payloads: list[object] = []
            page.on("response", _capture_graphql_json(captured_json_payloads))
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _wait_for_network_idle(page, timeout_ms)
            return LocalBrowserPageSnapshot(
                status_code=response.status if response is not None else None,
                final_url=str(page.url),
                content=_append_captured_json_payloads(
                    str(page.content()),
                    captured_json_payloads,
                ),
            )
        finally:
            browser.close()


def _browser_context_options() -> dict[str, object]:
    return {
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
        "viewport": {"width": 1365, "height": 768},
        "user_agent": _DESKTOP_USER_AGENT,
        "extra_http_headers": {"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.6"},
    }


def _capture_graphql_json(captured_payloads: list[object]) -> Callable[[Any], None]:
    def capture(response: Any) -> None:
        if len(captured_payloads) >= 10:
            return
        if "/graphql/" not in str(getattr(response, "url", "")):
            return
        if int(getattr(response, "status", 0)) != 200:
            return
        try:
            payload = response.json()
        except Exception:
            return
        if isinstance(payload, dict):
            captured_payloads.append(payload)

    return capture


def _append_captured_json_payloads(content: str, payloads: list[object]) -> str:
    if not payloads:
        return content
    scripts = "".join(
        (
            '<script type="application/json" '
            'data-monitor-cashback-live-json="citilink_graphql">'
            f"{_safe_json_script_payload(payload)}</script>"
        )
        for payload in payloads
    )
    marker = "</body>"
    if marker in content:
        return content.replace(marker, f"{scripts}{marker}", 1)
    return f"{content}{scripts}"


def _safe_json_script_payload(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _playwright_proxy_config(proxy_url: str) -> dict[str, str]:
    parsed = urlsplit(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        return {"server": proxy_url}

    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        server = f"{server}:{parsed.port}"
    proxy = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


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


def _is_antibot_snapshot(snapshot: LocalBrowserPageSnapshot) -> bool:
    if snapshot.status_code in _BLOCKED_STATUSES:
        return True
    body = snapshot.content[:8192].lower()
    return any(marker in body for marker in _ANTIBOT_MARKERS)
