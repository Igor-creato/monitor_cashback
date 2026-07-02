import json

import httpx

from price_monitor.core.config import Settings
from price_monitor.domains.fetching.managed_unblocker_fetcher import (
    DecodoWebScrapingApiFetcher,
    build_managed_unblocker_fetcher,
)


def test_decodo_web_scraping_fetcher_posts_premium_headless_request_and_maps_response() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "content": "<html><title>Rendered product</title></html>",
                        "status_code": 200,
                        "task_id": "decodo-task-123",
                    }
                ]
            },
        )

    fetcher = DecodoWebScrapingApiFetcher(
        endpoint_url="https://scraper-api.decodo.com/v2/scrape",
        authorization_header="Basic decodo-token",  # noqa: S106
        timeout_seconds=5.0,
        proxy_pool="premium",
        headless="html",
        geo="Russia",
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(url="https://www.ozon.ru/product/123", proxy_url=None)

    assert result.content == "<html><title>Rendered product</title></html>"
    assert result.final_url == "https://www.ozon.ru/product/123"
    assert result.http_status == 200
    assert result.provider_name == "decodo-web-scraping-api"
    assert result.provider_request_id == "decodo-task-123"
    assert result.rendered is True
    assert captured == {
        "url": "https://scraper-api.decodo.com/v2/scrape",
        "authorization": "Basic decodo-token",
        "payload": {
            "url": "https://www.ozon.ru/product/123",
            "proxy_pool": "premium",
            "headless": "html",
            "device_type": "desktop",
            "geo": "Russia",
        },
    }


def test_decodo_web_scraping_fetcher_accepts_http_error_when_result_content_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "results": [
                    {
                        "content": "<html><title>Blocked but billed result</title></html>",
                        "status_code": 403,
                        "task_id": "decodo-task-403",
                    }
                ]
            },
        )

    fetcher = DecodoWebScrapingApiFetcher(
        endpoint_url="https://scraper-api.decodo.com/v2/scrape",
        authorization_header="Basic decodo-token",  # noqa: S106
        timeout_seconds=5.0,
        proxy_pool="premium",
        headless="html",
        geo="",
        transport=httpx.MockTransport(handler),
    )

    result = fetcher.fetch(url="https://www.wildberries.ru/catalog/1/detail.aspx", proxy_url=None)

    assert result.content == "<html><title>Blocked but billed result</title></html>"
    assert result.http_status == 403
    assert result.provider_request_id == "decodo-task-403"


def test_build_managed_unblocker_fetcher_requires_decodo_token() -> None:
    assert build_managed_unblocker_fetcher(Settings(decodo_web_scraping_api_token="")) is None


def test_build_managed_unblocker_fetcher_uses_decodo_token_from_env_settings() -> None:
    fetcher = build_managed_unblocker_fetcher(
        Settings(decodo_web_scraping_api_token="decodo-token")  # noqa: S106
    )

    assert isinstance(fetcher, DecodoWebScrapingApiFetcher)


def test_decodo_default_timeout_allows_js_rendering_latency() -> None:
    assert Settings().decodo_web_scraping_timeout_seconds == 60.0
