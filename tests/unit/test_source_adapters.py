from __future__ import annotations

from decimal import Decimal

import pytest

from price_monitor.domains.fetching.ports import FetchPageResult
from price_monitor.domains.fetching.sources.base import FetchContext
from price_monitor.domains.fetching.sources.registry import get_adapter_for_source


class StaticFetcher:
    def __init__(self, html: str) -> None:
        self._html = html

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        return FetchPageResult(
            content=self._html,
            final_url=url,
            http_status=200,
            response_ms=15,
        )


def test_generic_adapter_returns_confident_extraction() -> None:
    adapter = get_adapter_for_source("example.com")
    result = adapter.fetch_product(
        FetchContext(
            canonical_url="https://example.com/p/1",
            source_domain="example.com",
            source_product_id=None,
            strategy="direct_http",
            fetcher=StaticFetcher(
                """
                <script type="application/ld+json">
                {"@type":"Product","name":"Phone","image":"https://img.test/p.jpg",
                "offers":{"price":"123.45","priceCurrency":"RUB"},
                "aggregateRating":{"ratingValue":"4.8"}}
                </script>
                """
            ),
            proxy_url=None,
            fallback_currency="RUB",
        )
    )

    assert result.status == "ok"
    assert result.extraction is not None
    assert result.extraction.title == "Phone"
    assert result.extraction.price_minor == 12345
    assert result.extraction.currency == "RUB"
    assert result.extraction.source_product_id is None
    assert result.extraction.confidence == Decimal("0.90")
    assert result.parser_version == "generic-html-v1"
    assert result.parser_confidence == "0.90"
    assert result.provider_name is None
    assert result.provider_request_id is None
    assert result.provider_cost_minor is None
    assert result.rendered is False


def test_generic_adapter_uses_low_confidence_for_meta_only_extraction() -> None:
    adapter = get_adapter_for_source("example.com")
    result = adapter.fetch_product(
        FetchContext(
            canonical_url="https://example.com/p/2",
            source_domain="example.com",
            source_product_id="sku-2",
            strategy="direct_http",
            fetcher=StaticFetcher(
                """
                <meta property="og:title" content="Smart Watch">
                <meta property="og:image" content="https://img.test/watch.jpg">
                <meta property="product:price:amount" content="990">
                <meta property="product:price:currency" content="RUB">
                """
            ),
            proxy_url=None,
            fallback_currency="RUB",
        )
    )

    assert result.status == "ok"
    assert result.extraction is not None
    assert result.extraction.source_product_id == "sku-2"
    assert result.extraction.confidence == Decimal("0.40")
    assert result.parser_version == "generic-html-v1"
    assert result.parser_confidence == "0.40"
    assert result.provider_name is None
    assert result.provider_request_id is None
    assert result.provider_cost_minor is None
    assert result.rendered is False


@pytest.mark.parametrize(
    ("source_domain", "parser_version"),
    (
        ("aliexpress.com", "aliexpress-v1"),
        ("citilink.ru", "citilink-v1"),
        ("joom.com", "joom-v1"),
        ("wildberries.ru", "wildberries-v1"),
        ("ozon.ru", "ozon-v1"),
        ("market.yandex.ru", "yandex-market-v1"),
    ),
)
def test_required_store_adapters_extract_fixture_product(
    source_domain: str,
    parser_version: str,
) -> None:
    adapter = get_adapter_for_source(source_domain)
    result = adapter.fetch_product(
        FetchContext(
            canonical_url=f"https://{source_domain}/fixture-product",
            source_domain=source_domain,
            source_product_id="123456789",
            strategy="direct_http",
            fetcher=StaticFetcher(
                """
                <script type="application/ld+json">
                {"@type":"Product","name":"Phone","image":"https://img.test/p.jpg",
                "offers":{"price":"123.45","priceCurrency":"RUB"}}
                </script>
                """
            ),
            proxy_url=None,
            fallback_currency="RUB",
        )
    )

    assert result.status == "ok"
    assert result.extraction is not None
    assert result.extraction.title == "Phone"
    assert result.extraction.price_minor == 12345
    assert result.parser_version == parser_version
