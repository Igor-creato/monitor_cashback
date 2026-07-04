from __future__ import annotations

import hmac
from base64 import b64encode
from hashlib import sha256
from typing import Any

import httpx
import pytest

from price_monitor.core.config import Settings
from price_monitor.price_compare.wordpress_bridge import (
    WordPressBridgeUnavailable,
    WordPressInternalBridgeClient,
    redact_wordpress_bridge_payload,
)


def test_wordpress_bridge_client_signs_internal_hmac_like_wordpress() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        captured["headers"] = request.headers
        return httpx.Response(200, json={"status": "ok", "affiliate_url": "https://go.test/1"})

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = WordPressInternalBridgeClient(
        Settings(
            wordpress_internal_base_url="https://wp.test",
            wordpress_internal_site="price-monitor-test",
            wordpress_internal_secret="wp-secret",
        ),
        http_client=http_client,
        clock=lambda: 1_700_000_000,
    )

    response = client.create_deeplink(
        "admitad",
        "https://shop.test/product/1",
        offer_id="campaign-10",
    )

    expected_signature = hmac.new(
        b"wp-secret",
        (
            b'1700000000.{"network":"admitad",'
            b'"source_url":"https://shop.test/product/1",'
            b'"offer_id":"campaign-10"}'
        ),
        sha256,
    ).hexdigest()
    assert response["affiliate_url"] == "https://go.test/1"
    assert captured["path"] == "/wp-json/savello-internal/v1/price-comparison/cpa/deeplink"
    assert captured["headers"]["X-Savello-Site"] == "price-monitor-test"
    assert captured["headers"]["X-Savello-Timestamp"] == "1700000000"
    assert captured["headers"]["X-Savello-Signature"] == expected_signature
    assert captured["body"] == (
        b'{"network":"admitad","source_url":"https://shop.test/product/1","offer_id":"campaign-10"}'
    )


def test_wordpress_bridge_client_requires_internal_settings() -> None:
    client = WordPressInternalBridgeClient(Settings())

    with pytest.raises(WordPressBridgeUnavailable) as exc:
        client.network_statuses()

    assert "wordpress internal bridge is not configured" in str(exc.value)
    assert "secret" not in str(exc.value).lower()


def test_wordpress_bridge_client_downloads_feed_content_from_internal_json() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "content_base64": b64encode(b"id;title\n1;Phone\n").decode("ascii"),
                "content_type": "text/csv",
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = WordPressInternalBridgeClient(
        Settings(
            wordpress_internal_base_url="https://wp.test",
            wordpress_internal_site="price-monitor-test",
            wordpress_internal_secret="wp-secret",
        ),
        http_client=http_client,
        clock=lambda: 1_700_000_000,
    )

    content = client.download_feed(
        {
            "network": "admitad",
            "store_domain": "merchant.test",
            "offer_id": "campaign-10",
            "feed_id": "feed-csv",
        }
    )

    assert content == b"id;title\n1;Phone\n"
    assert captured["path"] == "/wp-json/savello-internal/v1/price-comparison/cpa/feed-content"
    assert b"wp-secret" not in captured["body"]


def test_wordpress_bridge_redacts_secret_like_payload_values() -> None:
    payload = {
        "api_key": "advcake-key",
        "client_secret": "admitad-secret",
        "feed_url": "https://feed.test/feed.xml?pass=secret-token",
        "items": [{"url": "https://shop.test/product/1"}],
    }

    redacted = redact_wordpress_bridge_payload(payload)
    encoded = repr(redacted)

    assert "advcake-key" not in encoded
    assert "admitad-secret" not in encoded
    assert "secret-token" not in encoded
    assert "https://shop.test/product/1" in encoded
