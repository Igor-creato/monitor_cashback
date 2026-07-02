from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Protocol

import httpx

from price_monitor.core.config import Settings
from price_monitor.core.url_policy import validate_public_product_url
from price_monitor.domains.fetching.ports import FetchPageResult, ProductPageFetcher


class BrowserProviderUnavailableError(RuntimeError):
    """Raised when no approved browser/provider adapter is configured for a URL."""


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

        payload = {
            "url": url,
            "source_domain": source_domain,
            "wait_selector": wait_selector,
            "proxy_url": proxy_url,
        }
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(self._endpoint_url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("rendered HTML provider request failed") from exc

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


def build_source_browser_fetcher(settings: Settings) -> ProductPageFetcher | None:
    if not settings.joom_browser_provider_url.strip():
        return None

    provider = HttpRenderedHtmlProvider(
        endpoint_url=settings.joom_browser_provider_url,
        bearer_token=settings.joom_browser_provider_token,
        timeout_seconds=settings.joom_browser_provider_timeout_seconds,
    )
    return SourceAwareBrowserFetcher(
        {
            "joom.ru": JoomBrowserProviderFetcher(
                provider=provider,
                wait_selector=settings.joom_browser_provider_wait_selector,
            )
        }
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
