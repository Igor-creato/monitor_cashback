from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.transports.base import (
    TransportNetworkError,
    TransportResponse,
    TransportTimeoutError,
    TransportUnavailableError,
)

# Допустимые impersonate-профили -> значение, понятное curl_cffi.
_IMPERSONATE_PROFILES: dict[str, str] = {
    "chrome": "chrome",
    "chrome_android": "chrome_android",
    "safari": "safari",
}


class CurlCffiTransport:
    """Adapter поверх curl_cffi для browser-like TLS/HTTP fingerprint fetch.

    curl_cffi импортируется лениво при первом вызове fetch(), чтобы импорт
    этого модуля и тесты не требовали установленного пакета и системных
    зависимостей.
    """

    def __init__(
        self,
        *,
        impersonate: str = "chrome",
        requests_module: Any | None = None,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        if impersonate not in _IMPERSONATE_PROFILES:
            raise ValueError(
                f"unsupported impersonate profile: {impersonate!r}; "
                f"allowed: {sorted(_IMPERSONATE_PROFILES)}"
            )
        self._impersonate = _IMPERSONATE_PROFILES[impersonate]
        self._requests_module = requests_module
        self._time_provider = time_provider or time.monotonic

    def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        proxy_url: str | None = None,
        timeout: float | None = None,
    ) -> TransportResponse:
        requests_module = self._get_requests_module()
        exceptions = requests_module.exceptions

        kwargs: dict[str, Any] = {"impersonate": self._impersonate}
        if headers is not None:
            kwargs["headers"] = headers
        if proxy_url is not None:
            kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
        if timeout is not None:
            kwargs["timeout"] = timeout

        started = self._time_provider()
        try:
            response = requests_module.get(url, **kwargs)
        except exceptions.Timeout as exc:
            raise TransportTimeoutError(str(exc)) from exc
        except exceptions.RequestsError as exc:
            raise TransportNetworkError(str(exc)) from exc
        elapsed_ms = int((self._time_provider() - started) * 1000)

        headers_map = dict(response.headers)
        return TransportResponse(
            status_code=response.status_code,
            headers=headers_map,
            text=response.text,
            content_type=headers_map.get("Content-Type", ""),
            elapsed_ms=elapsed_ms,
            final_url=str(response.url),
        )

    def _get_requests_module(self) -> Any:
        if self._requests_module is not None:
            return self._requests_module
        try:
            from curl_cffi import requests as curl_requests
        except ImportError as exc:
            raise TransportUnavailableError(
                "curl_cffi is not installed; install the optional 'curl_cffi' "
                "package to use CurlCffiTransport"
            ) from exc
        return curl_requests
