from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol
from urllib.parse import urlparse

import httpx

from price_monitor.core.config import Settings
from price_monitor.core.url_policy import validate_public_product_url
from price_monitor.domains.fetching.ports import FetchPageResult, ProductPageFetcher


class BrowserProviderUnavailableError(RuntimeError):
    """Raised when no approved browser/provider adapter is configured for a URL."""


@dataclass(frozen=True)
class SourceBrowserFetcherConfig:
    joom_browser_provider_url: str
    joom_browser_provider_token: str
    joom_browser_provider_timeout_seconds: float
    joom_browser_provider_wait_selector: str


class RenderedHtmlProvider(Protocol):
    def render(
        self,
        *,
        url: str,
        source_domain: str,
        wait_selector: str | None,
        proxy_url: str | None,
    ) -> FetchPageResult:
        """Render a public product URL and return HTML."""


class HttpRenderedHtmlProvider:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bearer_token: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._bearer_token = bearer_token
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def render(
        self,
        *,
        url: str,
        source_domain: str,
        wait_selector: str | None,
        proxy_url: str | None,
    ) -> FetchPageResult:
        started = perf_counter()
        headers = {}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"

        payload = self._request_payload(
            url=url,
            source_domain=source_domain,
            wait_selector=wait_selector,
            proxy_url=proxy_url,
        )
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(self._endpoint_url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("rendered HTML provider request failed") from exc

        if self._returns_html_content():
            return FetchPageResult(
                content=response.text,
                final_url=response.headers.get("x-response-url") or url,
                http_status=_int_header(response, "x-response-code") or response.status_code,
                response_ms=max(0, int((perf_counter() - started) * 1000)),
            )

        body = _json_object(response)
        content = _string_field(body, "content") or _string_field(body, "html")
        if content is None:
            raise RuntimeError("rendered HTML provider returned no content")

        response_ms = _int_field(body, "response_ms")
        if response_ms is None:
            response_ms = max(0, int((perf_counter() - started) * 1000))

        return FetchPageResult(
            content=content,
            final_url=_string_field(body, "final_url") or url,
            http_status=_int_field(body, "http_status") or response.status_code,
            response_ms=response_ms,
        )

    def _request_payload(
        self,
        *,
        url: str,
        source_domain: str,
        wait_selector: str | None,
        proxy_url: str | None,
    ) -> dict[str, object]:
        if self._is_browserless_content_endpoint():
            timeout_ms = max(1000, int(self._timeout_seconds * 1000))
            payload: dict[str, object] = {
                "url": url,
                "bestAttempt": True,
                "gotoOptions": {"waitUntil": "networkidle2", "timeout": timeout_ms},
            }
            if wait_selector:
                payload["waitForSelector"] = {
                    "selector": wait_selector,
                    "timeout": timeout_ms,
                }
            return payload

        return {
            "url": url,
            "source_domain": source_domain,
            "wait_selector": wait_selector,
            "proxy_url": proxy_url,
        }

    def _is_browserless_content_endpoint(self) -> bool:
        return urlparse(self._endpoint_url).path.rstrip("/").endswith("/content")

    def _returns_html_content(self) -> bool:
        return self._is_browserless_content_endpoint()


class JoomBrowserProviderFetcher:
    def __init__(
        self,
        *,
        provider: RenderedHtmlProvider,
        wait_selector: str = 'meta[property="product:price:amount"]',
    ) -> None:
        self._provider = provider
        self._wait_selector = wait_selector

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        return self._provider.render(
            url=url,
            source_domain="joom.ru",
            wait_selector=self._wait_selector,
            proxy_url=proxy_url,
        )


class SourceAwareBrowserFetcher:
    def __init__(self, adapters: Mapping[str, ProductPageFetcher]) -> None:
        self._adapters = dict(adapters)

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        hostname = validate_public_product_url(url).source_domain
        adapter = self._adapter_for_hostname(hostname)
        if adapter is None:
            raise BrowserProviderUnavailableError(
                f"browser provider is not configured for {hostname}"
            )
        return adapter.fetch(url=url, proxy_url=proxy_url)

    def _adapter_for_hostname(self, hostname: str) -> ProductPageFetcher | None:
        matches = [
            (source_domain, adapter)
            for source_domain, adapter in self._adapters.items()
            if hostname == source_domain or hostname.endswith(f".{source_domain}")
        ]
        if not matches:
            return None
        return max(matches, key=lambda match: len(match[0]))[1]


def build_source_browser_fetcher(
    settings: Settings,
    stored_settings: Mapping[str, str] | None = None,
) -> ProductPageFetcher | None:
    config = resolve_source_browser_fetcher_config(settings, stored_settings)
    if not config.joom_browser_provider_url.strip():
        return None

    provider = HttpRenderedHtmlProvider(
        endpoint_url=config.joom_browser_provider_url,
        bearer_token=config.joom_browser_provider_token,
        timeout_seconds=config.joom_browser_provider_timeout_seconds,
    )
    return SourceAwareBrowserFetcher(
        {
            "joom.ru": JoomBrowserProviderFetcher(
                provider=provider,
                wait_selector=config.joom_browser_provider_wait_selector,
            )
        }
    )


def resolve_source_browser_fetcher_config(
    settings: Settings,
    stored_settings: Mapping[str, str] | None = None,
) -> SourceBrowserFetcherConfig:
    return SourceBrowserFetcherConfig(
        joom_browser_provider_url=_setting_string(
            stored_settings,
            "joom_browser_provider_url",
            settings.joom_browser_provider_url,
        ),
        joom_browser_provider_token=_setting_string(
            stored_settings,
            "joom_browser_provider_token",
            settings.joom_browser_provider_token,
        ),
        joom_browser_provider_timeout_seconds=_setting_float(
            stored_settings,
            "joom_browser_provider_timeout_seconds",
            settings.joom_browser_provider_timeout_seconds,
        ),
        joom_browser_provider_wait_selector=_setting_string(
            stored_settings,
            "joom_browser_provider_wait_selector",
            settings.joom_browser_provider_wait_selector,
        ),
    )


def _json_object(response: httpx.Response) -> dict[str, object]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise RuntimeError("rendered HTML provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("rendered HTML provider returned a non-object payload")
    return payload


def _string_field(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _int_field(payload: dict[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _int_header(response: httpx.Response, key: str) -> int | None:
    value = response.headers.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _setting_string(
    stored_settings: Mapping[str, str] | None,
    key: str,
    fallback: str,
) -> str:
    if stored_settings is not None:
        value = stored_settings.get(key)
        if value is not None and value.strip():
            return value.strip()
    return fallback.strip()


def _setting_float(
    stored_settings: Mapping[str, str] | None,
    key: str,
    fallback: float,
) -> float:
    if stored_settings is not None:
        value = stored_settings.get(key)
        if value is not None and value.strip():
            try:
                parsed = float(value)
            except ValueError:
                return fallback
            if parsed > 0:
                return parsed
    return fallback
