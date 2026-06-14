from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import Settings, settings
from app.fetchers.base import FetchError


@dataclass(frozen=True)
class BrowserFetchResult:
    final_url: str
    html: str
    screenshot_object_key: str | None
    response_status: int | None
    elapsed_ms: int
    browser_engine: str
    debug_info: dict[str, Any] = field(default_factory=dict)


class BrowserClient(Protocol):
    def fetch_rendered_html(
        self,
        url: str,
        *,
        proxy_url: str | None,
        timeout: float | None,
        wait_until: str,
        screenshot_store: ScreenshotStore | None,
    ) -> BrowserFetchResult:  # pragma: no cover - protocol only
        ...


class ScreenshotStore(Protocol):
    def store_screenshot(
        self,
        content: bytes,
        metadata: dict[str, Any],
    ) -> str:  # pragma: no cover - protocol only
        ...


class BrowserUnavailableError(Exception):
    """Browser adapter is unavailable because config/dependency/connection failed."""


class BrowserPageFetcher:
    def __init__(
        self,
        *,
        browser_client: BrowserClient | None = None,
        screenshot_store: ScreenshotStore | None = None,
        settings: Settings = settings,
    ) -> None:
        self._browser_client = browser_client or PlaywrightBrowserClient(
            settings=settings
        )
        self._screenshot_store = screenshot_store

    def fetch_rendered_html(
        self,
        url: str,
        proxy_url: str | None = None,
        timeout: float | None = None,
        wait_until: str = "networkidle",
    ) -> BrowserFetchResult:
        try:
            result = self._browser_client.fetch_rendered_html(
                url,
                proxy_url=proxy_url,
                timeout=timeout,
                wait_until=wait_until,
                screenshot_store=self._screenshot_store,
            )
        except TimeoutError as exc:
            raise FetchError("timeout") from exc
        except BrowserUnavailableError as exc:
            raise FetchError("browser_unavailable") from exc

        return result


class PlaywrightBrowserClient:
    def __init__(
        self,
        *,
        settings: Settings = settings,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings
        self._time_provider = time_provider or time.monotonic

    def fetch_rendered_html(
        self,
        url: str,
        *,
        proxy_url: str | None,
        timeout: float | None,
        wait_until: str,
        screenshot_store: ScreenshotStore | None,
    ) -> BrowserFetchResult:
        endpoint = self._browserless_endpoint()
        timeout_ms = int(timeout * 1000) if timeout is not None else None

        try:
            from playwright.sync_api import (
                Error as PlaywrightError,
            )
            from playwright.sync_api import (
                TimeoutError as PlaywrightTimeoutError,
            )
            from playwright.sync_api import (
                sync_playwright,
            )
        except ImportError as exc:
            raise BrowserUnavailableError("playwright is not installed") from exc

        started = self._time_provider()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(endpoint)
                try:
                    context_options: dict[str, Any] = {}
                    if proxy_url is not None:
                        context_options["proxy"] = {"server": proxy_url}
                    context = browser.new_context(**context_options)
                    try:
                        page = context.new_page()
                        response = page.goto(
                            url,
                            wait_until=wait_until,
                            timeout=timeout_ms,
                        )
                        html = page.content()
                        screenshot_bytes = (
                            page.screenshot(full_page=True)
                            if screenshot_store is not None
                            else None
                        )
                        final_url = page.url
                        response_status = (
                            response.status if response is not None else None
                        )
                    finally:
                        context.close()
                finally:
                    browser.close()
        except PlaywrightTimeoutError as exc:
            raise TimeoutError(str(exc)) from exc
        except PlaywrightError as exc:
            raise BrowserUnavailableError("browser request failed") from exc

        elapsed_ms = int((self._time_provider() - started) * 1000)
        screenshot_object_key = None
        if screenshot_store is not None and screenshot_bytes is not None:
            screenshot_object_key = screenshot_store.store_screenshot(
                screenshot_bytes,
                {
                    "final_url": final_url,
                    "response_status": response_status,
                    "browser_engine": "chromium",
                },
            )

        return BrowserFetchResult(
            final_url=final_url,
            html=html,
            screenshot_object_key=screenshot_object_key,
            response_status=response_status,
            elapsed_ms=elapsed_ms,
            browser_engine="chromium",
            debug_info={
                "adapter": "playwright",
                "remote": True,
                "proxy_enabled": proxy_url is not None,
                "wait_until": wait_until,
            },
        )

    def _browserless_endpoint(self) -> str:
        endpoint = self._settings.browserless_ws_url.strip()
        if not endpoint:
            raise BrowserUnavailableError("BROWSERLESS_WS_URL is not configured")

        token = self._settings.browserless_token.get_secret_value().strip()
        if not token:
            return endpoint

        parsed = urlsplit(endpoint)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("token", token)
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query),
                parsed.fragment,
            )
        )
