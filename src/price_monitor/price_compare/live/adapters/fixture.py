from __future__ import annotations

from decimal import Decimal
from typing import Any

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_OK,
    LiveSearchItem,
    LiveSearchQuery,
    LiveStoreResult,
)
from price_monitor.price_compare.schemas import normalize_domain


class FixtureSearchAdapter:
    def __init__(self, *, domain: str, items: list[dict[str, Any]]) -> None:
        self._domain = normalize_domain(domain)
        self._items = items

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        items: list[LiveSearchItem] = []
        for raw_item in self._items[: query.limit]:
            items.append(
                LiveSearchItem(
                    title=str(raw_item.get("title", "")),
                    price=_price_or_none(raw_item.get("price")),
                    url=str(raw_item.get("url", "")),
                    availability=str(raw_item.get("availability", "unknown")),
                    store_domain=self._domain,
                    store_name=str(raw_item.get("store_name", self._domain)),
                    currency=str(raw_item.get("currency", "RUB")),
                    image_url=_optional_string(raw_item.get("image_url")),
                    category=_optional_string(raw_item.get("category")),
                    brand=_optional_string(raw_item.get("brand")),
                    external_id=_optional_string(raw_item.get("external_id")),
                )
            )
        return LiveStoreResult(store_domain=self._domain, status=STORE_STATUS_OK, items=items)


def _price_or_none(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
