from decimal import Decimal

import httpx

from price_monitor.price_compare.live.adapters.base import LiveSearchQuery
from price_monitor.price_compare.live.adapters.decodo import DecodoWebSearchAdapter
from price_monitor.price_compare.live.adapters.registry import get_adapter_for_store


def test_decodo_adapter_posts_scrape_request_and_parses_citilink_json_ld() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "status_code": 200,
                        "task_id": "task_123",
                        "content": """
                        <html><head>
                        <script type="application/ld+json">
                        {
                          "@context": "https://schema.org",
                          "@type": "ItemList",
                          "itemListElement": [
                            {
                              "@type": "ListItem",
                              "item": {
                                "@type": "Product",
                                "name": "Телевизор Hisense 55E7NQ",
                                "url": "https://www.citilink.ru/product/tv-123/",
                                "image": "https://items.citilink.ru/tv.jpg",
                                "offers": {
                                  "@type": "Offer",
                                  "price": "39990",
                                  "priceCurrency": "RUB",
                                  "availability": "https://schema.org/InStock"
                                }
                              }
                            }
                          ]
                        }
                        </script>
                        </head></html>
                        """,
                    }
                ]
            },
        )

    adapter = DecodoWebSearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        api_url="https://scraper-api.decodo.com/v2/scrape",
        auth_token="token-value",
        parser="citilink_search_v1",
        headless="html",
        proxy_pool="premium",
        device_type="desktop",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "ok"
    assert result.items[0].title == "Телевизор Hisense 55E7NQ"
    assert result.items[0].price == Decimal("39990")
    assert result.items[0].url == "https://www.citilink.ru/product/tv-123/"
    assert result.items[0].availability == "in_stock"
    assert requests[0].headers["authorization"] == "Basic token-value"
    assert requests[0].headers["accept"] == "application/json"
    assert requests[0].url == "https://scraper-api.decodo.com/v2/scrape"
    assert requests[0].read()
    payload = requests[0].content.decode("utf-8")
    assert '"proxy_pool":"premium"' in payload
    assert '"headless":"html"' in payload
    assert '"device_type":"desktop"' in payload
    assert "%D1%82%D0%B5%D0%BB%D0%B5%D0%B2%D0%B8%D0%B7%D0%BE%D1%80" in payload


def test_decodo_adapter_returns_safe_failure_when_provider_cannot_scrape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "failed",
                "status_code": 613,
                "message": "We were not able to scrape the target.",
                "task_id": "task_613",
            },
        )

    adapter = DecodoWebSearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        api_url="https://scraper-api.decodo.com/v2/scrape",
        auth_token="token-value",
        parser="citilink_search_v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "failed"
    assert result.items == []
    assert result.warnings == ["decodo_scrape_failed"]
    assert result.message == "Провайдер поиска не смог получить страницу магазина"


def test_registry_builds_decodo_adapter_for_managed_provider(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_DECODO_BASIC_AUTH_TOKEN", "token-value")
    monkeypatch.setenv(
        "PRICE_MONITOR_DECODO_SCRAPER_API_URL", "https://scraper-api.decodo.com/v2/scrape"
    )

    adapter = get_adapter_for_store(
        "citilink.ru",
        {
            "source_type": "managed_provider",
            "source_config": {
                "provider": "decodo",
                "live_search_url_template": "https://www.citilink.ru/search/?text={query}",
                "parser": "citilink_search_v1",
                "proxy_pool": "premium",
            },
        },
    )

    assert isinstance(adapter, DecodoWebSearchAdapter)
