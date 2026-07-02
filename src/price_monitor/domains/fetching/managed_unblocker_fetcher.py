from __future__ import annotations

from base64 import b64encode
from time import perf_counter
from typing import Any

import httpx

from price_monitor.core.config import Settings
from price_monitor.domains.fetching.ports import FetchPageResult, ProductPageFetcher

DECODO_PROVIDER_NAME = "decodo-web-scraping-api"


class DecodoWebScrapingApiFetcher:
    def __init__(
        self,
        *,
        endpoint_url: str,
        authorization_header: str,
        timeout_seconds: float,
        proxy_pool: str,
        headless: str,
        geo: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._authorization_header = authorization_header
        self._timeout_seconds = timeout_seconds
        self._proxy_pool = proxy_pool
        self._headless = headless
        self._geo = geo
        self._transport = transport

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        del proxy_url
        started = perf_counter()
        payload: dict[str, object] = {
            "url": url,
            "proxy_pool": self._proxy_pool,
            "headless": self._headless,
            "device_type": "desktop",
        }
        if self._geo.strip():
            payload["geo"] = self._geo.strip()

        try:
            with httpx.Client(timeout=self._timeout_seconds, transport=self._transport) as client:
                response = client.post(
                    self._endpoint_url,
                    json=payload,
                    headers={"Authorization": self._authorization_header},
                )
        except httpx.RequestError as exc:
            raise RuntimeError("managed unblocker request failed") from exc

        result = _first_result(response)
        content = _string_field(result, "content")
        if content is None:
            raise RuntimeError("managed unblocker returned no content")

        response_ms = max(0, int((perf_counter() - started) * 1000))
        return FetchPageResult(
            content=content,
            final_url=_string_field(result, "url") or url,
            http_status=_int_field(result, "status_code") or response.status_code,
            response_ms=response_ms,
            provider_name=DECODO_PROVIDER_NAME,
            provider_request_id=_string_field(result, "task_id"),
            rendered=self._headless.strip().lower() in {"html", "true", "1"},
        )


def build_managed_unblocker_fetcher(settings: Settings) -> ProductPageFetcher | None:
    authorization_header = _authorization_header(settings)
    if not authorization_header:
        return None

    return DecodoWebScrapingApiFetcher(
        endpoint_url=settings.decodo_web_scraping_api_url,
        authorization_header=authorization_header,
        timeout_seconds=settings.decodo_web_scraping_timeout_seconds,
        proxy_pool=settings.decodo_web_scraping_proxy_pool,
        headless=settings.decodo_web_scraping_headless,
        geo=settings.decodo_web_scraping_geo,
    )


def _authorization_header(settings: Settings) -> str:
    token = settings.decodo_web_scraping_api_token.strip()
    if token:
        if token.lower().startswith("basic "):
            return token
        return f"Basic {token}"

    username = settings.decodo_web_scraping_username.strip()
    password = settings.decodo_web_scraping_password.strip()
    if username and password:
        encoded = b64encode(f"{username}:{password}".encode()).decode()
        return f"Basic {encoded}"
    return ""


def _first_result(response: httpx.Response) -> dict[str, Any]:
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise RuntimeError("managed unblocker returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("managed unblocker returned a non-object payload")

    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError("managed unblocker returned no results")

    result = results[0]
    if not isinstance(result, dict):
        raise RuntimeError("managed unblocker returned an invalid result")
    return result


def _string_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _int_field(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None
