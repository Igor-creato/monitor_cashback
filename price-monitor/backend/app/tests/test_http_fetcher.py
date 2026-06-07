import socket
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.fetchers.base import FetchError
from app.fetchers.http_fetcher import HTTPPriceFetcher

NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


def _fetcher_for(handler) -> HTTPPriceFetcher:
    return HTTPPriceFetcher(
        transport=httpx.MockTransport(handler),
        time_provider=lambda: NOW,
    )


def test_json_fixture_extracts_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://testshop.local/product/123"
        return httpx.Response(
            200,
            json={
                "product_name": "Test Phone",
                "price_current": "1999.90",
                "price_old": "2499.00",
                "currency": "RUB",
                "availability": True,
                "seller_name": "Test Seller",
                "image_url": "https://testshop.local/images/123.jpg",
            },
            headers={"Content-Type": "application/json"},
        )

    result = _fetcher_for(handler).fetch("https://testshop.local/product/123")

    assert result.product_name == "Test Phone"
    assert result.price_current == Decimal("1999.90")
    assert result.price_old == Decimal("2499.00")
    assert result.currency == "RUB"
    assert result.availability is True
    assert result.seller_name == "Test Seller"
    assert result.image_url == "https://testshop.local/images/123.jpg"
    assert result.fetched_at == NOW


def test_html_fixture_extracts_price() -> None:
    html = """
    <html>
      <body
        data-product-name="Demo Coat"
        data-price-current="3490.50"
        data-price-old="3990.00"
        data-currency="RUB"
        data-availability="true"
        data-seller-name="Demo Seller"
        data-image-url="https://demo-store.local/images/coat.jpg">
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://demo-store.local/goods/coat-42"
        return httpx.Response(
            200,
            content=html.encode(),
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    result = _fetcher_for(handler).fetch("https://demo-store.local/goods/coat-42")

    assert result.product_name == "Demo Coat"
    assert result.price_current == Decimal("3490.50")
    assert result.price_old == Decimal("3990.00")
    assert result.currency == "RUB"
    assert result.availability is True
    assert result.seller_name == "Demo Seller"
    assert result.image_url == "https://demo-store.local/images/coat.jpg"
    assert result.fetched_at == NOW


def test_403_maps_to_http_403() -> None:
    fetcher = _fetcher_for(lambda request: httpx.Response(403))

    with pytest.raises(FetchError) as exc_info:
        fetcher.fetch("https://testshop.local/product/123")

    assert exc_info.value.error_type == "http_403"


def test_429_maps_to_http_429() -> None:
    fetcher = _fetcher_for(lambda request: httpx.Response(429))

    with pytest.raises(FetchError) as exc_info:
        fetcher.fetch("https://testshop.local/product/123")

    assert exc_info.value.error_type == "http_429"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (
            b'{"product_name":"No price","currency":"RUB","availability":true}',
            "application/json",
        ),
        (
            b'<body data-product-name="No price" data-currency="RUB"></body>',
            "text/html",
        ),
    ],
)
def test_missing_price_maps_to_price_not_found(
    content: bytes,
    content_type: str,
) -> None:
    fetcher = _fetcher_for(
        lambda request: httpx.Response(
            200,
            content=content,
            headers={"Content-Type": content_type},
        )
    )

    with pytest.raises(FetchError) as exc_info:
        fetcher.fetch("https://testshop.local/product/123")

    assert exc_info.value.error_type == "price_not_found"


def test_timeout_maps_to_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    fetcher = _fetcher_for(handler)

    with pytest.raises(FetchError) as exc_info:
        fetcher.fetch("https://testshop.local/product/123")

    assert exc_info.value.error_type == "timeout"


def test_fetcher_uses_injected_transport_without_network(monkeypatch) -> None:
    network_calls = 0

    def fail_on_network(*args, **kwargs):
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("fetcher must not open real network connections")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "price_current": "100.00",
                "currency": "RUB",
                "availability": True,
            },
            headers={"Content-Type": "application/json"},
        )

    monkeypatch.setattr(socket, "create_connection", fail_on_network)

    result = _fetcher_for(handler).fetch("https://testshop.local/product/123")

    assert result.price_current == Decimal("100.00")
    assert network_calls == 0
