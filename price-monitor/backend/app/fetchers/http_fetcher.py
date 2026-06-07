from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

import httpx

from app.fetchers.base import FetchError, PriceFetchResult


class HTTPPriceFetcher:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        time_provider: Callable[[], datetime] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._client = client or httpx.Client(transport=transport, timeout=timeout)
        self._time_provider = time_provider or (
            lambda: datetime.now(UTC)
        )

    def fetch(self, url: str) -> PriceFetchResult:
        try:
            response = self._client.get(url)
        except httpx.TimeoutException as exc:
            raise FetchError("timeout") from exc
        except httpx.RequestError as exc:
            raise FetchError("source_unavailable") from exc

        self._raise_for_status(response)
        content_type = response.headers.get("Content-Type", "").lower()

        if not response.content:
            raise FetchError("bad_content")
        if "application/json" in content_type:
            return self._parse_json(response)
        if "text/html" in content_type:
            return self._parse_html(response)
        raise FetchError("bad_content")

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 403:
            raise FetchError("http_403")
        if response.status_code == 429:
            raise FetchError("http_429")
        if response.status_code >= 500:
            raise FetchError("source_unavailable")
        if response.status_code >= 400:
            raise FetchError("bad_content")

    def _parse_json(self, response: httpx.Response) -> PriceFetchResult:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FetchError("parser_error") from exc
        if not isinstance(payload, dict):
            raise FetchError("parser_error")
        return self._result_from_mapping(payload)

    def _parse_html(self, response: httpx.Response) -> PriceFetchResult:
        parser = _FixtureHTMLParser()
        try:
            parser.feed(response.text)
        except Exception as exc:
            raise FetchError("parser_error") from exc
        if parser.attributes is None:
            raise FetchError("parser_error")
        return self._result_from_mapping(parser.attributes)

    def _result_from_mapping(self, payload: dict[str, Any]) -> PriceFetchResult:
        return PriceFetchResult(
            product_name=_optional_str(payload.get("product_name")),
            price_current=_required_price(payload.get("price_current")),
            price_old=_optional_price(payload.get("price_old")),
            currency=_required_str(payload.get("currency"), default="RUB"),
            availability=_bool_value(payload.get("availability"), default=True),
            seller_name=_optional_str(payload.get("seller_name")),
            image_url=_optional_str(payload.get("image_url")),
            fetched_at=self._time_provider(),
        )


class _FixtureHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.attributes: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data_attrs = {
            key.removeprefix("data-").replace("-", "_"): value
            for key, value in attrs
            if key.startswith("data-") and value is not None
        }
        if data_attrs:
            self.attributes = data_attrs


def _required_price(value: Any) -> Decimal:
    price = _optional_price(value)
    if price is None:
        raise FetchError("price_not_found")
    return price


def _optional_price(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FetchError("price_not_found") from exc


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _required_str(value: Any, *, default: str) -> str:
    normalized = _optional_str(value)
    return normalized or default


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "available"}
    return bool(value)
