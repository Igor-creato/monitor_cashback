from __future__ import annotations

from time import perf_counter

import httpx

from price_monitor.domains.fetching.ports import FetchPageResult


class HttpProductPageFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        started = perf_counter()
        try:
            with httpx.Client(
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                },
                proxy=proxy_url,
                transport=self._transport,
            ) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"product page fetch failed: {exc}") from exc

        response_ms = max(0, int((perf_counter() - started) * 1000))
        return FetchPageResult(
            content=response.text,
            final_url=str(response.url),
            http_status=response.status_code,
            response_ms=response_ms,
        )
