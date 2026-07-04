from __future__ import annotations

import hmac
import json
import time
from base64 import b64decode
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from price_monitor.core.config import Settings, get_settings

_INTERNAL_BASE = "/wp-json/savello-internal/v1/price-comparison/cpa"
_SECRET_KEYS = {
    "access_token",
    "api_key",
    "client_id",
    "client_secret",
    "feed_url",
    "password",
    "products_csv_link",
    "products_xml_link",
    "refresh_token",
    "secret",
    "token",
}
_SECRET_QUERY_KEYS = {
    "access_token",
    "api_key",
    "auth",
    "key",
    "pass",
    "password",
    "secret",
    "token",
}


class WordPressBridgeUnavailable(RuntimeError):
    """Raised when the WordPress internal bridge cannot be used safely."""


class WordPressInternalBridgeClient:
    """Client for WordPress internal CPA bridge routes.

    WordPress verifies these requests with Savello_Internal_HMAC_Auth_Service,
    whose signature contract is HMAC-SHA256 over "timestamp.raw_body".
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._clock = clock

    def network_statuses(self) -> dict[str, Any]:
        return self._request_json("GET", f"{_INTERNAL_BASE}/networks")

    def feed_descriptors(self) -> dict[str, Any]:
        return self._request_json("GET", f"{_INTERNAL_BASE}/feeds")

    def download_feed(self, descriptor: Mapping[str, Any]) -> bytes:
        payload = {
            "network": descriptor.get("network", ""),
            "store_domain": descriptor.get("store_domain", ""),
            "offer_id": descriptor.get("offer_id", ""),
            "feed_id": descriptor.get("feed_id", ""),
        }
        response = self._request(
            "POST",
            f"{_INTERNAL_BASE}/feed-content",
            payload,
            accept="application/json",
        )
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("content_base64"), str):
            raise WordPressBridgeUnavailable(
                "wordpress internal bridge returned invalid feed content"
            )
        return b64decode(data["content_base64"], validate=True)

    def create_deeplink(self, network: str, source_url: str) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"{_INTERNAL_BASE}/deeplink",
            {"network": network, "source_url": source_url},
        )

    def _request_json(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._request(method, path, payload)
        data = response.json()
        if not isinstance(data, dict):
            raise WordPressBridgeUnavailable("wordpress internal bridge returned invalid json")
        return data

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        accept: str = "application/json",
    ) -> httpx.Response:
        self._ensure_configured()
        body = _json_body(payload)
        headers = self._signed_headers(body)
        headers["Accept"] = accept
        client = self._http_client or httpx.Client(
            timeout=self._settings.wordpress_internal_timeout_seconds
        )
        response = client.request(method, self._url(path), content=body, headers=headers)
        response.raise_for_status()
        return response

    def _ensure_configured(self) -> None:
        if (
            not self._settings.wordpress_internal_base_url.strip()
            or not self._settings.wordpress_internal_secret.strip()
        ):
            raise WordPressBridgeUnavailable("wordpress internal bridge is not configured")

    def _url(self, path: str) -> str:
        return f"{self._settings.wordpress_internal_base_url.rstrip('/')}{path}"

    def _signed_headers(self, body: bytes) -> dict[str, str]:
        timestamp = str(int(self._clock()))
        secret = self._settings.wordpress_internal_secret
        signature = hmac.new(
            secret.encode("utf-8"),
            timestamp.encode("utf-8") + b"." + body,
            sha256,
        ).hexdigest()
        return {
            "Content-Type": "application/json",
            "X-Savello-Site": self._settings.wordpress_internal_site,
            "X-Savello-Timestamp": timestamp,
            "X-Savello-Signature": signature,
        }


def redact_wordpress_bridge_payload(value: object) -> object:
    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_string = str(key)
            if key_string.lower() in _SECRET_KEYS:
                redacted[key_string] = "[redacted]"
            else:
                redacted[key_string] = redact_wordpress_bridge_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_wordpress_bridge_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_wordpress_bridge_payload(item) for item in value)
    if isinstance(value, str) and _url_has_secret_query(value):
        return "[redacted]"
    return value


def _json_body(payload: Mapping[str, Any] | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _url_has_secret_query(value: str) -> bool:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.query:
        return False
    return any(key.lower() in _SECRET_QUERY_KEYS for key, _ in parse_qsl(parsed.query))
