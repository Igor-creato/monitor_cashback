from decimal import Decimal

from price_monitor.price_compare.live.adapters.base import (
    STORE_STATUS_BLOCKED_BY_ANTIBOT,
    STORE_STATUS_FAILED,
    STORE_STATUS_OK,
    LiveSearchItem,
    LiveSearchQuery,
    LiveStoreResult,
)
from price_monitor.price_compare.live.adapters.chain import ProviderChainSearchAdapter


class RecordingAdapter:
    def __init__(
        self,
        name: str,
        result: LiveStoreResult,
        calls: list[str],
    ) -> None:
        self._name = name
        self._result = result
        self._calls = calls

    def search(self, query: LiveSearchQuery) -> LiveStoreResult:
        self._calls.append(self._name)
        return self._result


def test_provider_chain_tries_next_provider_after_safe_failures_and_empty_results() -> None:
    calls: list[str] = []
    item = LiveSearchItem(
        title="Смартфон Xiaomi Redmi Note 13",
        price=Decimal("17990"),
        url="https://citilink.ru/product/redmi-note-13/",
    )
    adapter = ProviderChainSearchAdapter(
        domain="citilink.ru",
        providers=[
            RecordingAdapter(
                "nodemaven",
                LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_FAILED,
                    warnings=["nodemaven_request_failed"],
                ),
                calls,
            ),
            RecordingAdapter(
                "local_browser",
                LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_OK,
                    items=[],
                    warnings=["local_browser_no_items"],
                ),
                calls,
            ),
            RecordingAdapter(
                "nodemaven_browser",
                LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_OK,
                    items=[item],
                ),
                calls,
            ),
        ],
    )

    result = adapter.search(LiveSearchQuery(query="redmi note 13", city="Москва", limit=5))

    assert calls == ["nodemaven", "local_browser", "nodemaven_browser"]
    assert result.status == STORE_STATUS_OK
    assert result.items == [item]


def test_provider_chain_stops_immediately_after_antibot_block() -> None:
    calls: list[str] = []
    adapter = ProviderChainSearchAdapter(
        domain="citilink.ru",
        providers=[
            RecordingAdapter(
                "nodemaven",
                LiveStoreResult(
                    store_domain="citilink.ru",
                    status=STORE_STATUS_BLOCKED_BY_ANTIBOT,
                    warnings=["blocked_by_antibot"],
                    message="Магазин ограничил автоматический доступ",
                ),
                calls,
            ),
            RecordingAdapter(
                "local_browser",
                LiveStoreResult(store_domain="citilink.ru", status=STORE_STATUS_OK),
                calls,
            ),
        ],
    )

    result = adapter.search(LiveSearchQuery(query="redmi note 13", city="Москва", limit=5))

    assert calls == ["nodemaven"]
    assert result.status == STORE_STATUS_BLOCKED_BY_ANTIBOT
    assert result.warnings == ["blocked_by_antibot"]
