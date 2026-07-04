from decimal import Decimal

from price_monitor.core.config import get_settings
from price_monitor.price_compare.live.adapters.base import LiveSearchQuery
from price_monitor.price_compare.live.adapters.nodemaven_browser import (
    BrowserPageSnapshot,
    NodeMavenBrowserSearchAdapter,
)
from price_monitor.price_compare.live.adapters.registry import get_adapter_for_store


def test_nodemaven_browser_adapter_fetches_rendered_page_and_parses_citilink_json_ld() -> None:
    requests: list[tuple[str, str]] = []

    def fetcher(browser_ws_url: str, target_url: str, timeout_ms: int) -> BrowserPageSnapshot:
        requests.append((browser_ws_url, target_url))
        assert timeout_ms == 120_000
        return BrowserPageSnapshot(
            status_code=200,
            final_url=target_url,
            content="""
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
                    "name": "Ноутбук ASUS Vivobook 15",
                    "url": "/product/noutbuk-asus-vivobook-15/",
                    "image": "/images/asus-vivobook.jpg",
                    "brand": "ASUS",
                    "sku": "7654321",
                    "offers": {
                      "@type": "Offer",
                      "price": "54990",
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
        )

    adapter = NodeMavenBrowserSearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        browser_ws_url="wss://proxy-user_country-ru-sid-test:proxy-pass@browser.nodemaven.com",
        parser="citilink_search_v1",
        timeout_seconds=120,
        fetcher=fetcher,
    )

    result = adapter.search(LiveSearchQuery(query="asus vivobook", city="Москва", limit=5))

    assert result.status == "ok"
    assert result.items[0].title == "Ноутбук ASUS Vivobook 15"
    assert result.items[0].price == Decimal("54990")
    assert result.items[0].url == "https://citilink.ru/product/noutbuk-asus-vivobook-15/"
    assert result.items[0].brand == "ASUS"
    assert requests == [
        (
            "wss://proxy-user_country-ru-sid-test:proxy-pass@browser.nodemaven.com",
            "https://www.citilink.ru/search/?text=asus%20vivobook",
        )
    ]


def test_nodemaven_browser_adapter_returns_safe_failure_when_url_is_missing() -> None:
    adapter = NodeMavenBrowserSearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        browser_ws_url="",
        parser="citilink_search_v1",
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Москва", limit=5))

    assert result.status == "failed"
    assert result.items == []
    assert result.warnings == ["nodemaven_browser_not_configured"]
    assert result.message == "Провайдер поиска не настроен"


def test_nodemaven_browser_adapter_marks_antibot_response() -> None:
    adapter = NodeMavenBrowserSearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        browser_ws_url="wss://proxy-user_country-ru-sid-test:proxy-pass@browser.nodemaven.com",
        parser="citilink_search_v1",
        fetcher=lambda browser_ws_url, target_url, timeout_ms: BrowserPageSnapshot(
            status_code=429,
            final_url=target_url,
            content="<html><body>too many requests</body></html>",
        ),
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Москва", limit=5))

    assert result.status == "BLOCKED_BY_ANTIBOT"
    assert result.items == []
    assert result.warnings == ["blocked_by_antibot"]
    assert result.message == "Магазин ограничил автоматический доступ"


def test_registry_builds_nodemaven_browser_adapter_for_managed_provider(monkeypatch) -> None:
    monkeypatch.setenv(
        "PRICE_MONITOR_NODEMAVEN_BROWSER_WS_URL",
        "wss://proxy-user_country-ru-sid-test:proxy-pass@browser.nodemaven.com",
    )
    get_settings.cache_clear()

    adapter = get_adapter_for_store(
        "citilink.ru",
        {
            "source_type": "managed_provider",
            "source_config": {
                "provider": "nodemaven_browser",
                "live_search_url_template": "https://www.citilink.ru/search/?text={query}",
                "parser": "citilink_search_v1",
            },
        },
    )

    assert isinstance(adapter, NodeMavenBrowserSearchAdapter)
