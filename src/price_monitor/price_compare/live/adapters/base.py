from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

STORE_STATUS_OK = "ok"
STORE_STATUS_BLOCKED_BY_ANTIBOT = "BLOCKED_BY_ANTIBOT"
STORE_STATUS_FAILED = "failed"
STORE_STATUS_DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class LiveSearchQuery:
    query: str
    city: str
    limit: int


@dataclass(frozen=True, slots=True)
class LiveSearchItem:
    title: str
    price: Decimal | None
    url: str
    availability: str = "unknown"
    store_domain: str = ""
    store_name: str = ""
    currency: str = "RUB"
    image_url: str | None = None
    category: str | None = None
    brand: str | None = None
    external_id: str | None = None
    relevance_reason: str = ""


@dataclass(frozen=True, slots=True)
class LiveStoreStatus:
    store_domain: str
    status: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class LiveStoreResult:
    store_domain: str
    status: str
    items: list[LiveSearchItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""


class SearchAdapter(Protocol):
    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        """Search a store and return safe normalized items."""
