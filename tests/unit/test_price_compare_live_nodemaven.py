from decimal import Decimal

import httpx

from price_monitor.core.config import get_settings
from price_monitor.price_compare.live.adapters.base import LiveSearchQuery
from price_monitor.price_compare.live.adapters.nodemaven import NodeMavenProxySearchAdapter
from price_monitor.price_compare.live.adapters.registry import get_adapter_for_store


def test_nodemaven_adapter_gets_search_page_and_parses_citilink_json_ld() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text="""
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

    adapter = NodeMavenProxySearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        proxy_url="http://proxy-user:proxy-pass@gate.nodemaven.com:8080",
        parser="citilink_search_v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = adapter.search(LiveSearchQuery(query="redmi note 13", city="Пенза", limit=5))

    assert result.status == "ok"
    assert result.items[0].title == "Смартфон Xiaomi Redmi Note 13"
    assert result.items[0].price == Decimal("17990")
    assert result.items[0].url == "https://citilink.ru/product/smartfon-xiaomi-redmi-note-13/"
    assert result.items[0].availability == "in_stock"
    assert result.items[0].brand == "Xiaomi"
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://www.citilink.ru/search/?text=redmi%20note%2013"


def test_nodemaven_adapter_returns_safe_failure_when_credentials_are_missing() -> None:
    adapter = NodeMavenProxySearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        proxy_url="",
        parser="citilink_search_v1",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "failed"
    assert result.items == []
    assert result.warnings == ["nodemaven_not_configured"]
    assert result.message == "Провайдер поиска не настроен"


def test_nodemaven_adapter_can_be_constructed_without_proxy_credentials() -> None:
    adapter = NodeMavenProxySearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        proxy_url="",
        parser="citilink_search_v1",
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "failed"
    assert result.warnings == ["nodemaven_not_configured"]


def test_nodemaven_adapter_marks_antibot_response() -> None:
    adapter = NodeMavenProxySearchAdapter(
        domain="citilink.ru",
        search_url_template="https://www.citilink.ru/search/?text={query}",
        proxy_url="http://proxy-user:proxy-pass@gate.nodemaven.com:8080",
        parser="citilink_search_v1",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, text="captcha required")
            )
        ),
    )

    result = adapter.search(LiveSearchQuery(query="телевизор", city="Пенза", limit=5))

    assert result.status == "BLOCKED_BY_ANTIBOT"
    assert result.items == []
    assert result.warnings == ["blocked_by_antibot"]
    assert result.message == "Магазин ограничил автоматический доступ"


def test_registry_builds_nodemaven_adapter_for_managed_provider(monkeypatch) -> None:
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_USERNAME", "proxy-user")
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_PASSWORD", "proxy-pass")
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_HOST", "gate.nodemaven.com")
    monkeypatch.setenv("PRICE_MONITOR_NODEMAVEN_PROXY_PORT", "8080")
    get_settings.cache_clear()

    adapter = get_adapter_for_store(
        "citilink.ru",
        {
            "source_type": "managed_provider",
            "source_config": {
                "provider": "nodemaven",
                "live_search_url_template": "https://www.citilink.ru/search/?text={query}",
                "parser": "citilink_search_v1",
            },
        },
    )

    assert isinstance(adapter, NodeMavenProxySearchAdapter)
