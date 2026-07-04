from decimal import Decimal

from price_monitor.core.config import get_settings
from price_monitor.price_compare.live.adapters.base import LiveSearchQuery
from price_monitor.price_compare.live.adapters.chain import ProviderChainSearchAdapter
from price_monitor.price_compare.live.adapters.local_browser import (
    LocalBrowserPageSnapshot,
    LocalBrowserSearchAdapter,
)
from price_monitor.price_compare.live.adapters.nodemaven import NodeMavenProxySearchAdapter
from price_monitor.price_compare.live.adapters.nodemaven_browser import (
    NodeMavenBrowserSearchAdapter,
)
from price_monitor.price_compare.live.adapters.registry import get_adapter_for_store


def test_local_browser_adapter_fetches_rendered_page_and_parses_citilink_json_ld() -> None:
    requests: list[tuple[str, int, str]] = []

    def fetcher(target_url: str, timeout_ms: int, proxy_url: str) -> LocalBrowserPageSnapshot:
        requests.append((target_url, timeout_ms, proxy_url))
        return LocalBrowserPageSnapshot(
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
                    "name": "Смартфон Xiaomi Redmi Note 13",
                    "url": "/product/smartfon-xiaomi-redmi-note-13/",
                    "image": "/images/redmi-note-13.jpg",
                    "brand": {"@type": "Brand", "name": "Xiaomi"},
                    "sku": "1234567",
                    "offers": {
                      "@type": "Offer",
                      "price": "17990",
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

    adapter = LocalBrowserSearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        parser="citilink_search_v1",
        proxy_url="http://proxy-user:proxy-pass@gate.nodemaven.com:8080",
        timeout_seconds=120,
        fetcher=fetcher,
    )

    result = adapter.search(LiveSearchQuery(query="redmi note 13", city="Москва", limit=5))

    assert result.status == "ok"
    assert result.items[0].title == "Смартфон Xiaomi Redmi Note 13"
    assert result.items[0].price == Decimal("17990")
    assert result.items[0].url == "https://citilink.ru/product/smartfon-xiaomi-redmi-note-13/"
    assert result.items[0].brand == "Xiaomi"
    assert requests == [
        (
            "https://www.citilink.ru/search/?text=redmi%20note%2013",
            120_000,
            "http://proxy-user:proxy-pass@gate.nodemaven.com:8080",
        )
    ]


def test_registry_builds_chain_with_local_browser_using_nodemaven_proxy(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_USERNAME", "proxy-user")
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_PASSWORD", "proxy-pass")
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_HOST", "gate.nodemaven.com")
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_PORT", "8080")
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
                "provider": "chain",
                "live_search_url_template": "https://www.citilink.ru/search/?text={query}",
                "parser": "citilink_search_v1",
                "providers": [
                    {"provider": "nodemaven"},
                    {"provider": "local_browser", "proxy": "nodemaven"},
                    {"provider": "nodemaven_browser"},
                ],
            },
        },
    )

    assert isinstance(adapter, ProviderChainSearchAdapter)
    assert len(adapter.providers) == 3
    assert isinstance(adapter.providers[0], NodeMavenProxySearchAdapter)
    assert isinstance(adapter.providers[1], LocalBrowserSearchAdapter)
    assert isinstance(adapter.providers[2], NodeMavenBrowserSearchAdapter)
    assert adapter.providers[1].proxy_url == "http://proxy-user:proxy-pass@gate.nodemaven.com:8080"
