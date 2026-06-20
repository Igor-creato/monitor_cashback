import hashlib
import hmac
import json
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings, settings

API_PREFIX = "/wp-json/savello-internal/v1"


class CashbackAPIError(Exception):
    """Base exception for the external cashback internal API client."""


class CashbackAPIAuthError(CashbackAPIError):
    """Raised when the external API rejects HMAC authentication."""


class CashbackAPINotFoundError(CashbackAPIError):
    """Raised when the external API returns 404."""


class CashbackAPIBadResponseError(CashbackAPIError):
    """Raised when the external API returns malformed or unexpected data."""


class CashbackAPIUnavailableError(CashbackAPIError):
    """Raised when the external API is temporarily unavailable."""


class CashbackAPIClient:
    def __init__(
        self,
        *,
        settings: Settings = settings,
        transport: httpx.BaseTransport | None = None,
        time_provider: Callable[[], int | float] | None = None,
    ) -> None:
        self._settings = settings
        self._site_id = settings.cashback_api_site_id.strip()
        self._secret = settings.cashback_api_secret
        self._time_provider = time_provider or time.time
        self._client = httpx.Client(
            base_url=settings.cashback_api_base_url.rstrip("/"),
            timeout=settings.cashback_api_timeout_seconds,
            transport=transport,
        )

    def __repr__(self) -> str:
        return (
            "CashbackAPIClient("
            f"base_url={self._settings.cashback_api_base_url!r}, "
            f"site_id={self._site_id!r})"
        )

    def get_manifest(self) -> Any:
        return self._request("GET", "/manifest")

    def get_merchants(
        self,
        status: str = "active",
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        return self._request(
            "GET",
            "/merchants",
            params={"status": status, "limit": limit, "offset": offset},
        )

    def get_merchant_rates(self, merchant_id: str) -> Any:
        escaped_merchant_id = quote(str(merchant_id), safe="")
        return self._request("GET", f"/merchants/{escaped_merchant_id}/rates")

    def resolve_product(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/resolve-product", payload=payload)

    def create_deeplink(self, payload: dict[str, Any]) -> Any:
        return self._request("POST", "/deeplink", payload=payload)

    def send_price_monitor_notification(self, payload: dict[str, Any]) -> Any:
        response = self._request(
            "POST",
            "/price-monitor/notifications",
            payload=payload,
        )
        if not isinstance(response, dict) or response.get("status") not in {
            "queued",
            "sent",
        }:
            raise CashbackAPIBadResponseError(
                "Cashback API returned invalid notification response."
            )
        return response

    def get_user_price_monitor_limits(self, external_user_id: str) -> Any:
        escaped_user_id = quote(str(external_user_id), safe="")
        return self._request(
            "GET",
            f"/users/{escaped_user_id}/price-monitor-limits",
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        raw_body = self._raw_json_body(payload) if payload is not None else b""
        headers = self._auth_headers(raw_body)
        if payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            response = self._client.request(
                method,
                f"{API_PREFIX}{path}",
                content=raw_body if payload is not None else None,
                params=params,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise CashbackAPIUnavailableError("Cashback API request failed.") from exc

        self._raise_for_status(response)

        try:
            return response.json()
        except ValueError as exc:
            raise CashbackAPIBadResponseError(
                "Cashback API returned invalid JSON."
            ) from exc

    def _auth_headers(self, raw_body: bytes) -> dict[str, str]:
        timestamp = str(int(self._time_provider()))
        secret = self._secret.get_secret_value()
        signature = hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + raw_body,
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-Savello-Site": self._site_id,
            "X-Savello-Timestamp": timestamp,
            "X-Savello-Signature": signature,
        }

    @staticmethod
    def _raw_json_body(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, separators=(",", ":")).encode()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise CashbackAPIAuthError("Cashback API authentication failed.")
        if status_code == 404:
            raise CashbackAPINotFoundError("Cashback API resource was not found.")
        if status_code >= 500:
            raise CashbackAPIUnavailableError("Cashback API is unavailable.")
        raise CashbackAPIBadResponseError("Cashback API returned an error response.")
