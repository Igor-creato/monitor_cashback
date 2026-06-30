from __future__ import annotations

import httpx
import pytest

from price_monitor.domains.fetching.http_fetcher import HttpProductPageFetcher


def test_http_product_page_fetcher_returns_page_result_with_browser_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["user_agent"] = request.headers["user-agent"]
        seen["accept"] = request.headers["accept"]
        return httpx.Response(
            200,
            content=b"<html><title>Product</title></html>",
            request=request,
        )

    fetcher = HttpProductPageFetcher(transport=httpx.MockTransport(handler))

    result = fetcher.fetch(url="https://example.com/item?id=42", proxy_url=None)

    assert result.content == "<html><title>Product</title></html>"
    assert result.final_url == "https://example.com/item?id=42"
    assert result.http_status == 200
    assert result.response_ms >= 0
    assert "Mozilla/5.0" in seen["user_agent"]
    assert "text/html" in seen["accept"]


def test_http_product_page_fetcher_raises_runtime_error_for_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    fetcher = HttpProductPageFetcher(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="product page fetch failed"):
        fetcher.fetch(url="https://example.com/item?id=42", proxy_url=None)
