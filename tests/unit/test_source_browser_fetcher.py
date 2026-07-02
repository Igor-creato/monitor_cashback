import json

import httpx
import pytest

from price_monitor.core.config import Settings
from price_monitor.domains.fetching.ports import FetchPageResult
from price_monitor.domains.fetching.source_browser_fetcher import (
    BrowserProviderUnavailableError,
    HttpRenderedHtmlProvider,
    JoomBrowserProviderFetcher,
    SourceAwareBrowserFetcher,
    build_source_browser_fetcher,
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
