from __future__ import annotations

from dataclasses import dataclass

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    STORE_STATUS_OK,
    LiveSearchItem,
    LiveSearchQuery,
    LiveStoreResult,
)
from price_monitor.price_compare.live.adapters.chain import ProviderChainSearchAdapter


@dataclass
class _Provider:
    name: str
    calls: list[str]
    result: LiveStoreResult | None = None
    error: Exception | None = None

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        self.calls.append(self.name)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_provider_chain_tries_next_provider_after_safe_failures() -> None:
    calls: list[str] = []
    query = LiveSearchQuery(query="redmi note 13", city="Москва", limit=5)
    chain = ProviderChainSearchAdapter(
        domain="citilink.ru",
        providers=[
            _Provider("nodemaven", calls, error=TimeoutError("request timed out")),
            _Provider(
                "local_browser",
                calls,
                result=LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_OK,
                    items=[],
                    warnings=["local_browser_no_items"],
                ),
            ),
            _Provider(
                "nodemaven_browser",
                calls,
                result=LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_OK,
                    items=[
                        LiveSearchItem(
                            title="Смартфон Xiaomi Redmi Note 13",
                            price=None,
                            url="https://citilink.ru/product/redmi-note-13/",
                        )
                    ],
                    warnings=[],
                ),
            ),
        ],
    )

    result = chain.search(query)

    assert result.status == STORE_STATUS_OK
    assert result.items[0].title == "Смартфон Xiaomi Redmi Note 13"
    assert calls == ["nodemaven", "local_browser", "nodemaven_browser"]


def test_provider_chain_stops_on_antibot_without_trying_next_provider() -> None:
    calls: list[str] = []
    query = LiveSearchQuery(query="redmi note 13", city="Москва", limit=5)
    chain = ProviderChainSearchAdapter(
        domain="citilink.ru",
        providers=[
            _Provider(
                "nodemaven",
                calls,
                result=LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                    items=[],
                    warnings=["blocked_by_antibot"],
                    message="Магазин ограничил автоматический доступ",
                ),
            ),
            _Provider(
                "local_browser",
                calls,
                result=LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_FAILED,
                    items=[],
                ),
            ),
        ],
    )

    result = chain.search(query)

    assert result.status == STORE_STATUS_BLOCKED_BY_ANTIBOT
    assert result.warnings == ["blocked_by_antibot"]
    assert calls == ["nodemaven"]


def test_provider_chain_tries_browser_after_nodemaven_http_429_soft_block() -> None:
    calls: list[str] = []
    query = LiveSearchQuery(query="redmi note 13", city="Москва", limit=5)
    chain = ProviderChainSearchAdapter(
        domain="citilink.ru",
        providers=[
            _Provider(
                "nodemaven",
                calls,
                result=LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                    items=[],
                    warnings=[
                        "blocked_by_antibot",
                        "nodemaven_blocked_by_antibot",
                        "antibot_http_status_429",
                    ],
                    message="Магазин ограничил автоматический доступ",
                ),
            ),
            _Provider(
                "local_browser",
                calls,
                result=LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_OK,
                    items=[
                        LiveSearchItem(
                            title="Смартфон Xiaomi Redmi Note 13",
                            price=None,
                            url="https://www.citilink.ru/product/redmi-note-13-123/",
                        )
                    ],
                ),
            ),
        ],
    )

    result = chain.search(query)

    assert result.status == STORE_STATUS_OK
    assert result.items[0].title == "Смартфон Xiaomi Redmi Note 13"
    assert calls == ["nodemaven", "local_browser"]
