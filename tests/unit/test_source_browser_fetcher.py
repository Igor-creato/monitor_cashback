import json

import httpx
import pytest

from price_monitor.core.config import Settings
from price_monitor.domains.fetching import source_browser_fetcher as source_browser_fetcher_module
from price_monitor.domains.fetching.ports import FetchPageResult
from price_monitor.domains.fetching.source_browser_fetcher import (
    BrowserProviderUnavailableError,
    HttpRenderedHtmlProvider,
    JoomBrowserProviderFetcher,
    SourceAwareBrowserFetcher,
    SourceBrowserFetcherConfig,
    build_source_browser_fetcher,
    resolve_source_browser_fetcher_config,
)


class FakeFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        self.calls.append((url, proxy_url))
        return FetchPageResult(
            content="<html>rendered</html>",
            final_url=url,
            http_status=200,
            response_ms=11,
        )


def test_http_rendered_html_provider_posts_payload_and_maps_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "content": "<html><meta property='product:price:amount' content='990'></html>",
                "final_url": "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
                "http_status": 200,
                "response_ms": 321,
            },
        )

    provider = HttpRenderedHtmlProvider(
        endpoint_url="https://renderer.test/render",
        bearer_token="provider-secret",
        timeout_seconds=3.0,
        transport=httpx.MockTransport(handler),
    )

    result = provider.render(
        url="https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        source_domain="joom.ru",
        wait_selector='meta[property="product:price:amount"]',
        proxy_url=None,
    )

    assert result.content.startswith("<html>")
    assert result.final_url == "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5"
    assert result.http_status == 200
    assert result.response_ms == 321
    assert captured["url"] == "https://renderer.test/render"
    assert captured["authorization"] == "Bearer provider-secret"
    assert captured["payload"] == {
        "url": "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        "source_domain": "joom.ru",
        "wait_selector": 'meta[property="product:price:amount"]',
        "proxy_url": None,
    }


def test_http_rendered_html_provider_supports_browserless_content_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            text="<html><meta property='product:price:amount' content='990'></html>",
            headers={
                "content-type": "text/html; charset=utf-8",
                "x-response-code": "200",
                "x-response-url": "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
            },
        )

    provider = HttpRenderedHtmlProvider(
        endpoint_url="http://browserless.test:3000/chromium/content?token=browser-token",
        bearer_token="",
        timeout_seconds=12.5,
        transport=httpx.MockTransport(handler),
    )

    result = provider.render(
        url="https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        source_domain="joom.ru",
        wait_selector='meta[property="product:price:amount"]',
        proxy_url=None,
    )

    assert result.content.startswith("<html>")
    assert result.final_url == "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5"
    assert result.http_status == 200
    assert captured["url"] == "http://browserless.test:3000/chromium/content?token=browser-token"
    assert captured["authorization"] is None
    assert captured["payload"] == {
        "url": "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        "bestAttempt": True,
        "gotoOptions": {"waitUntil": "networkidle2", "timeout": 12500},
        "waitForSelector": {
            "selector": 'meta[property="product:price:amount"]',
            "timeout": 12500,
        },
    }


def test_joom_browser_provider_fetcher_requests_price_meta_wait_selector() -> None:
    captured: dict[str, object] = {}

    class FakeProvider:
        def render(
            self,
            *,
            url: str,
            source_domain: str,
            wait_selector: str | None,
            proxy_url: str | None,
        ) -> FetchPageResult:
            captured.update(
                {
                    "url": url,
                    "source_domain": source_domain,
                    "wait_selector": wait_selector,
                    "proxy_url": proxy_url,
                }
            )
            return FetchPageResult(
                content="<html>ok</html>",
                final_url=url,
                http_status=200,
                response_ms=9,
            )

    fetcher = JoomBrowserProviderFetcher(provider=FakeProvider())

    result = fetcher.fetch(
        url="https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        proxy_url="http://proxy.local:8080",
    )

    assert result.content == "<html>ok</html>"
    assert captured == {
        "url": "https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        "source_domain": "joom.ru",
        "wait_selector": 'meta[property="product:price:amount"]',
        "proxy_url": "http://proxy.local:8080",
    }


def test_source_aware_browser_fetcher_dispatches_joom_urls() -> None:
    fake = FakeFetcher()
    fetcher = SourceAwareBrowserFetcher({"joom.ru": fake})

    result = fetcher.fetch(
        url="https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5",
        proxy_url=None,
    )

    assert result.content == "<html>rendered</html>"
    assert fake.calls == [("https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5", None)]


def test_source_aware_browser_fetcher_dispatches_joom_com_urls() -> None:
    fake = FakeFetcher()
    fetcher = SourceAwareBrowserFetcher({"joom.com": fake})

    result = fetcher.fetch(
        url="https://www.joom.com/ru/products/60c584170413d901a6c20102",
        proxy_url=None,
    )

    assert result.content == "<html>rendered</html>"
    assert fake.calls == [("https://www.joom.com/ru/products/60c584170413d901a6c20102", None)]


def test_source_aware_browser_fetcher_fails_closed_for_unknown_source() -> None:
    fetcher = SourceAwareBrowserFetcher({"joom.ru": FakeFetcher()})

    with pytest.raises(BrowserProviderUnavailableError):
        fetcher.fetch(url="https://aliexpress.ru/item/1005010654381286.html", proxy_url=None)


def test_build_source_browser_fetcher_requires_joom_provider_url() -> None:
    settings = Settings(joom_browser_provider_url="", joom_browser_provider_token="")

    assert build_source_browser_fetcher(settings) is None


def test_build_source_browser_fetcher_returns_fetcher_when_joom_provider_is_configured() -> None:
    settings = Settings(
        joom_browser_provider_url="https://renderer.test/render",
        joom_browser_provider_token="provider-secret",
    )

    assert isinstance(build_source_browser_fetcher(settings), SourceAwareBrowserFetcher)


def test_build_source_browser_fetcher_dispatches_joom_com_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeProvider:
        def __init__(
            self,
            *,
            endpoint_url: str,
            bearer_token: str,
            timeout_seconds: float,
        ) -> None:
            captured["endpoint_url"] = endpoint_url
            captured["bearer_token"] = bearer_token
            captured["timeout_seconds"] = timeout_seconds

        def render(
            self,
            *,
            url: str,
            source_domain: str,
            wait_selector: str | None,
            proxy_url: str | None,
        ) -> FetchPageResult:
            captured.update(
                {
                    "url": url,
                    "source_domain": source_domain,
                    "wait_selector": wait_selector,
                    "proxy_url": proxy_url,
                }
            )
            return FetchPageResult(
                content="<html>joom</html>",
                final_url=url,
                http_status=200,
                response_ms=5,
            )

    monkeypatch.setattr(source_browser_fetcher_module, "HttpRenderedHtmlProvider", FakeProvider)
    settings = Settings(
        joom_browser_provider_url="https://renderer.test/render",
        joom_browser_provider_token="provider-secret",
    )

    fetcher = build_source_browser_fetcher(settings)
    assert fetcher is not None
    result = fetcher.fetch(
        url="https://www.joom.com/ru/products/60c584170413d901a6c20102",
        proxy_url=None,
    )

    assert result.content == "<html>joom</html>"
    assert captured == {
        "endpoint_url": "https://renderer.test/render",
        "bearer_token": "provider-secret",
        "timeout_seconds": 25.0,
        "url": "https://www.joom.com/ru/products/60c584170413d901a6c20102",
        "source_domain": "joom.com",
        "wait_selector": 'meta[property="product:price:amount"]',
        "proxy_url": None,
    }


def test_source_browser_fetcher_config_uses_admin_settings_before_env() -> None:
    settings = Settings(
        joom_browser_provider_url="https://env-renderer.test/render",
        joom_browser_provider_token="env-secret",
        joom_browser_provider_timeout_seconds=25.0,
        joom_browser_provider_wait_selector='meta[property="product:price:amount"]',
    )

    config = resolve_source_browser_fetcher_config(
        settings,
        {
            "joom_browser_provider_url": "https://admin-renderer.test/render",
            "joom_browser_provider_token": "admin-secret",
            "joom_browser_provider_timeout_seconds": "7.5",
            "joom_browser_provider_wait_selector": "#price",
        },
    )

    assert config == SourceBrowserFetcherConfig(
        joom_browser_provider_url="https://admin-renderer.test/render",
        joom_browser_provider_token="admin-secret",
        joom_browser_provider_timeout_seconds=7.5,
        joom_browser_provider_wait_selector="#price",
    )
