from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

import pytest

from app.fetchers.base import FetchError
from app.fetchers.browser_fetcher import (
    BrowserFetchResult,
    BrowserPageFetcher,
    BrowserUnavailableError,
)


@dataclass(frozen=True)
class _FakeBrowserResponse:
    final_url: str = "https://shop.local/p/1?rendered=1"
    html: str = "<html><body>Rendered product</body></html>"
    response_status: int | None = 200
    elapsed_ms: int = 125
    browser_engine: str = "fake-chromium"
    debug_info: dict[str, Any] | None = None
    screenshot_bytes: bytes | None = None


class _FakeBrowserClient:
    def __init__(
        self,
        *,
        response: _FakeBrowserResponse | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._response = response or _FakeBrowserResponse()
        self._raises = raises
        self.calls: list[dict[str, Any]] = []
        self.screenshot_calls = 0

    def fetch_rendered_html(
        self,
        url: str,
        *,
        proxy_url: str | None,
        timeout: float | None,
        wait_until: str,
        screenshot_store,
    ) -> BrowserFetchResult:
        self.calls.append(
            {
                "url": url,
                "proxy_url": proxy_url,
                "timeout": timeout,
                "wait_until": wait_until,
                "screenshot_enabled": screenshot_store is not None,
            }
        )
        if self._raises is not None:
            raise self._raises
        screenshot_object_key = None
        if screenshot_store is not None and self._response.screenshot_bytes is not None:
            self.screenshot_calls += 1
            screenshot_object_key = screenshot_store.store_screenshot(
                self._response.screenshot_bytes,
                {
                    "final_url": self._response.final_url,
                    "response_status": self._response.response_status,
                    "browser_engine": self._response.browser_engine,
                },
            )
        return BrowserFetchResult(
            final_url=self._response.final_url,
            html=self._response.html,
            screenshot_object_key=screenshot_object_key,
            response_status=self._response.response_status,
            elapsed_ms=self._response.elapsed_ms,
            browser_engine=self._response.browser_engine,
            debug_info=self._response.debug_info or {"adapter": "fake"},
        )


class _FakeScreenshotStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def store_screenshot(self, content: bytes, metadata: dict[str, Any]) -> str:
        self.calls.append({"content": content, "metadata": metadata})
        return "screenshots/rendered-page.png"


def test_fake_browser_returns_rendered_html() -> None:
    browser = _FakeBrowserClient()
    fetcher = BrowserPageFetcher(browser_client=browser)

    result = fetcher.fetch_rendered_html("https://shop.local/p/1")

    assert result.final_url == "https://shop.local/p/1?rendered=1"
    assert result.html == "<html><body>Rendered product</body></html>"
    assert result.screenshot_object_key is None
    assert result.response_status == 200
    assert result.elapsed_ms == 125
    assert result.browser_engine == "fake-chromium"
    assert result.debug_info == {"adapter": "fake"}
    assert browser.calls == [
        {
            "url": "https://shop.local/p/1",
            "proxy_url": None,
            "timeout": None,
            "wait_until": "networkidle",
            "screenshot_enabled": False,
        }
    ]


def test_timeout_maps_to_typed_fetch_error() -> None:
    browser = _FakeBrowserClient(raises=TimeoutError("browser timeout"))
    fetcher = BrowserPageFetcher(browser_client=browser)

    with pytest.raises(FetchError) as exc_info:
        fetcher.fetch_rendered_html("https://shop.local/p/1", timeout=3.5)

    assert exc_info.value.error_type == "timeout"


def test_proxy_is_passed_to_browser_options() -> None:
    browser = _FakeBrowserClient()
    fetcher = BrowserPageFetcher(browser_client=browser)

    fetcher.fetch_rendered_html(
        "https://shop.local/p/1",
        proxy_url="http://user:pass@127.0.0.1:8080",
        timeout=7.0,
        wait_until="domcontentloaded",
    )

    assert browser.calls[0]["proxy_url"] == "http://user:pass@127.0.0.1:8080"
    assert browser.calls[0]["timeout"] == 7.0
    assert browser.calls[0]["wait_until"] == "domcontentloaded"


def test_screenshot_is_not_captured_without_store() -> None:
    browser = _FakeBrowserClient(
        response=_FakeBrowserResponse(screenshot_bytes=b"png-bytes")
    )
    fetcher = BrowserPageFetcher(browser_client=browser)

    result = fetcher.fetch_rendered_html("https://shop.local/p/1")

    assert result.screenshot_object_key is None
    assert browser.screenshot_calls == 0


def test_screenshot_store_is_optional_and_receives_bytes() -> None:
    browser = _FakeBrowserClient(
        response=_FakeBrowserResponse(screenshot_bytes=b"png-bytes")
    )
    store = _FakeScreenshotStore()
    fetcher = BrowserPageFetcher(browser_client=browser, screenshot_store=store)

    result = fetcher.fetch_rendered_html("https://shop.local/p/1")

    assert result.screenshot_object_key == "screenshots/rendered-page.png"
    assert browser.screenshot_calls == 1
    assert store.calls == [
        {
            "content": b"png-bytes",
            "metadata": {
                "final_url": "https://shop.local/p/1?rendered=1",
                "response_status": 200,
                "browser_engine": "fake-chromium",
            },
        }
    ]


def test_browser_unavailable_maps_to_typed_fetch_error() -> None:
    browser = _FakeBrowserClient(raises=BrowserUnavailableError("no browser"))
    fetcher = BrowserPageFetcher(browser_client=browser)

    with pytest.raises(FetchError) as exc_info:
        fetcher.fetch_rendered_html("https://shop.local/p/1")

    assert exc_info.value.error_type == "browser_unavailable"


def test_unit_fetcher_does_not_open_real_browser_or_network(monkeypatch) -> None:
    network_calls = 0

    def fail_on_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("browser fetcher unit tests must not open network")

    monkeypatch.setattr(socket, "create_connection", fail_on_network)

    browser = _FakeBrowserClient()
    fetcher = BrowserPageFetcher(browser_client=browser)

    result = fetcher.fetch_rendered_html("https://shop.local/p/1")

    assert result.response_status == 200
    assert network_calls == 0
