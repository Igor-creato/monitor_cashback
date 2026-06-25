from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.fetchers.base import FetchError, PriceFetchResult
from app.fetchers.browser_fetcher import BrowserFetchResult
from app.models.monitoring import FetchAttempt, TrackedProduct
from app.services.fetch_strategy import FetchStrategyDecision
from app.services.user_limits import (
    CashbackLimitValues,
    PriceMonitorLimitValues,
    UserPriceMonitorLimits,
)

NOW = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@dataclass(frozen=True)
class _FeedItem:
    title: str = "Feed Product"
    price: Decimal = Decimal("1990.00")
    old_price: Decimal | None = Decimal("2490.00")
    currency: str = "RUB"
    availability: str = "in stock"
    image_url: str | None = "https://cdn.example/feed.jpg"
    updated_at: datetime = NOW


@dataclass(frozen=True)
class _Endpoint:
    pool_id: int
    id: int
    endpoint_ref: str


@dataclass(frozen=True)
class _Lease:
    lease_token: str
    endpoint: _Endpoint


@dataclass(frozen=True)
class _TransportResponse:
    status_code: int = 200
    text: str = (
        "<html><h1 class='title'>Transport Product</h1>"
        "<span class='price'>1234.50</span></html>"
    )
    content_type: str = "text/html"
    elapsed_ms: int = 111
    headers: dict[str, str] | None = None
    final_url: str = "https://shop.local/p/1"


class _FakeHTTPFetcher:
    def __init__(self, result: PriceFetchResult | Exception | None = None) -> None:
        self.result = result or _price_result(product_name="HTTP Product")
        self.calls: list[str] = []

    def fetch(self, url: str) -> PriceFetchResult:
        self.calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _FakeCurlTransport:
    def __init__(self, responses: list[_TransportResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        proxy_url: str | None = None,
        timeout: float | None = None,
    ) -> _TransportResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "proxy_url": proxy_url,
                "timeout": timeout,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeBrowserFetcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def fetch_rendered_html(
        self,
        url: str,
        proxy_url: str | None = None,
        timeout: float | None = None,
        wait_until: str = "networkidle",
    ) -> BrowserFetchResult:
        self.calls.append(
            {
                "url": url,
                "proxy_url": proxy_url,
                "timeout": timeout,
                "wait_until": wait_until,
            }
        )
        return BrowserFetchResult(
            final_url=url,
            html="<html><h1 class='title'>Browser Product</h1>"
            "<span class='price'>3456.70</span></html>",
            screenshot_object_key=None,
            response_status=200,
            elapsed_ms=250,
            browser_engine="fake-browser",
        )


def _product(session: Session, *, source: str = "testshop") -> TrackedProduct:
    tracked_product = TrackedProduct(
        source=source,
        external_product_id="sku-1",
        canonical_url=f"https://{source}.local/p/1",
        region_code="default",
    )
    session.add(tracked_product)
    session.commit()
    session.refresh(tracked_product)
    return tracked_product


def _decision(
    strategy: str,
    *,
    proxy_required: bool = False,
    proxy_tier: str | None = None,
    allow_fallback: bool = False,
    cost_level: str = "free",
) -> FetchStrategyDecision:
    return FetchStrategyDecision(
        strategy=strategy,
        reason=f"test_{strategy}",
        proxy_required=proxy_required,
        proxy_tier=proxy_tier,
        browser_required=strategy in {"crawl4ai", "playwright", "camoufox"},
        max_attempts=1,
        timeout_seconds=7,
        cost_level=cost_level,
        allow_fallback=allow_fallback,
    )


def _selector(decision: FetchStrategyDecision) -> Callable[..., FetchStrategyDecision]:
    def select_strategy(*args: Any, **kwargs: Any) -> FetchStrategyDecision:
        select_strategy.calls.append({"args": args, "kwargs": kwargs})
        return decision

    select_strategy.calls = []  # type: ignore[attr-defined]
    return select_strategy


def _schema(_tracked_product: TrackedProduct):
    from app.extraction import ExtractionSchema

    return ExtractionSchema(
        source_code="testshop",
        version="v1",
        content_type="html",
        css_title=".title",
        css_price=".price",
        required_fields=["title", "price_current"],
    )


def _price_result(*, product_name: str = "Product") -> PriceFetchResult:
    return PriceFetchResult(
        product_name=product_name,
        price_current=Decimal("1000.00"),
        price_old=None,
        currency="RUB",
        availability=True,
        seller_name=None,
        image_url="https://cdn.example/product.jpg",
        fetched_at=NOW,
    )


def _attempts(session: Session) -> list[FetchAttempt]:
    return list(session.scalars(select(FetchAttempt).order_by(FetchAttempt.id)).all())


def _attempt_count(session: Session) -> int:
    return session.scalar(select(func.count(FetchAttempt.id))) or 0


def _limits(*, browser_fallback_allowed: bool) -> UserPriceMonitorLimits:
    return UserPriceMonitorLimits(
        external_user_id="77",
        tariff="pro" if browser_fallback_allowed else "free",
        limits=PriceMonitorLimitValues(
            max_tracked_products=10,
            history_days=30,
            min_fetch_interval_minutes=60,
            alerts_per_day=10,
            manual_refresh_per_day=5,
            browser_fallback_allowed=browser_fallback_allowed,
        ),
        cashback=CashbackLimitValues(
            user_share=Decimal("0.5"),
            cashback_currency="RUB",
        ),
    )


def test_feed_strategy_uses_feed_item_and_skips_network(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)
    http_fetcher = _FakeHTTPFetcher()
    selector = _selector(_decision("feed"))

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=selector,
            find_feed_item=lambda tracked_product, *, session: _FeedItem(),
            feed_item_is_fresh=lambda feed_item, *, now: True,
            http_fetcher=http_fetcher,
            now=NOW,
        ),
    )

    assert result.product_name == "Feed Product"
    assert result.price_current == Decimal("1990.00")
    assert http_fetcher.calls == []
    assert _attempt_count(db_session) == 1
    assert _attempts(db_session)[0].strategy == "feed"


def test_direct_http_strategy_uses_http_fetcher_without_proxy(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)
    http_fetcher = _FakeHTTPFetcher()

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=_selector(_decision("direct_http")),
            find_feed_item=lambda tracked_product, *, session: None,
            http_fetcher=http_fetcher,
            now=NOW,
        ),
    )

    assert result.product_name == "HTTP Product"
    assert http_fetcher.calls == [product.canonical_url]
    assert _attempts(db_session)[0].proxy_endpoint_id is None


def test_wildberries_curl_strategy_uses_cards_api_product_data(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session, source="wildberries")
    product.external_product_id = "465676229"
    product.canonical_url = (
        "https://www.wildberries.ru/catalog/465676229/detail.aspx?targetUrl=EX"
    )
    db_session.commit()
    transport = _FakeCurlTransport([])
    cards_calls: list[dict[str, Any]] = []
    cards_response = _TransportResponse(
        text=(
            '{"products":[{"id":465676229,'
            '"brand":"AlaskaBurn",'
            '"name":"Сумка рюкзак спортивная для фитнеса",'
            '"totalQuantity":49,'
            '"sizes":[{"price":{"basic":700000,"product":140600}}]}]}'
        ),
        content_type="application/json",
    )

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=_selector(_decision("curl_cffi_http")),
            find_feed_item=lambda tracked_product, *, session: None,
            curl_transport=transport,
            wildberries_cards_fetcher=lambda url, timeout: (
                cards_calls.append({"url": url, "timeout": timeout}) or cards_response
            ),
            now=NOW,
        ),
    )

    assert result.product_name == "Сумка рюкзак спортивная для фитнеса"
    assert result.price_current == Decimal("1406.00")
    assert result.price_old == Decimal("7000.00")
    assert result.currency == "RUB"
    assert result.availability is True
    assert (
        result.image_url
        == "https://basket-26.wbbasket.ru/vol4656/part465676/465676229/images/big/1.webp"
    )
    assert transport.calls == []
    assert cards_calls == [
        {
            "url": (
                "https://card.wb.ru/cards/v4/detail?"
                "appType=1&curr=rub&dest=-1257786&spp=30&nm=465676229"
            ),
            "timeout": 7,
        }
    ]
    attempt = _attempts(db_session)[0]
    assert attempt.strategy == "curl_cffi_http"
    assert attempt.http_status == 200
    assert attempt.product_data_found is True
    assert attempt.price_found is True
    assert attempt.image_found is True


def test_wildberries_image_url_uses_extended_basket_range_for_new_articles() -> None:
    from app.services.multistage_fetch_executor import _wildberries_image_url

    assert _wildberries_image_url(853333396) == (
        "https://basket-38.wbbasket.ru/vol8533/part853333/853333396/images/big/1.webp"
    )


def test_wildberries_proxy_strategy_uses_cards_api_without_proxy_lease(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session, source="wildberries")
    product.external_product_id = "465676229"
    product.canonical_url = (
        "https://www.wildberries.ru/catalog/465676229/detail.aspx?targetUrl=EX"
    )
    db_session.commit()
    cards_calls: list[dict[str, Any]] = []
    cards_response = _TransportResponse(
        text=(
            '{"products":[{"id":465676229,'
            '"name":"Сумка рюкзак спортивная для фитнеса",'
            '"totalQuantity":49,'
            '"sizes":[{"price":{"product":140600}}]}]}'
        ),
        content_type="application/json",
    )

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=_selector(
                _decision(
                    "cheap_proxy_http",
                    proxy_required=True,
                    proxy_tier="cheap",
                )
            ),
            find_feed_item=lambda tracked_product, *, session: None,
            wildberries_cards_fetcher=lambda url, timeout: (
                cards_calls.append({"url": url, "timeout": timeout}) or cards_response
            ),
            proxy_leaser=lambda *args, **kwargs: pytest.fail(
                "wildberries cards API should not lease a proxy"
            ),
            now=NOW,
        ),
    )

    assert result.price_current == Decimal("1406.00")
    assert cards_calls == [
        {
            "url": (
                "https://card.wb.ru/cards/v4/detail?"
                "appType=1&curr=rub&dest=-1257786&spp=30&nm=465676229"
            ),
            "timeout": 7,
        }
    ]
    attempt = _attempts(db_session)[0]
    assert attempt.strategy == "cheap_proxy_http"
    assert attempt.proxy_pool_id is None
    assert attempt.proxy_endpoint_id is None
    assert attempt.status == "success"


def test_cheap_proxy_strategy_leases_proxy_and_reports_success(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)
    reports: list[dict[str, Any]] = []
    lease = _Lease(
        lease_token="lease-cheap",
        endpoint=_Endpoint(pool_id=10, id=20, endpoint_ref="http://cheap.proxy"),
    )
    transport = _FakeCurlTransport([_TransportResponse()])

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=_selector(
                _decision(
                    "cheap_proxy_http",
                    proxy_required=True,
                    proxy_tier="cheap",
                    cost_level="cheap",
                )
            ),
            find_feed_item=lambda tracked_product, *, session: None,
            curl_transport=transport,
            proxy_leaser=lambda source, purpose, job_id, **kwargs: lease,
            proxy_reporter=lambda token, status, event_type, response_ms, **kwargs: (
                reports.append(
                    {
                        "token": token,
                        "status": status,
                        "event_type": event_type,
                        "response_ms": response_ms,
                    }
                )
            ),
            schema_resolver=_schema,
            now=NOW,
        ),
    )

    assert result.product_name == "Transport Product"
    assert transport.calls[0]["proxy_url"] == "http://cheap.proxy"
    assert reports == [
        {
            "token": "lease-cheap",
            "status": "success",
            "event_type": "success",
            "response_ms": 111,
        }
    ]
    assert _attempts(db_session)[0].proxy_pool_id == 10
    assert _attempts(db_session)[0].proxy_endpoint_id == 20


def test_429_reports_failure_and_falls_back_to_next_proxy_tier(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)
    leases = [
        _Lease(
            lease_token="lease-cheap",
            endpoint=_Endpoint(pool_id=10, id=20, endpoint_ref="http://cheap.proxy"),
        ),
        _Lease(
            lease_token="lease-standard",
            endpoint=_Endpoint(pool_id=11, id=21, endpoint_ref="http://std.proxy"),
        ),
    ]
    reports: list[tuple[str, str, str, int | None]] = []
    transport = _FakeCurlTransport(
        [
            _TransportResponse(status_code=429, text="Too Many Requests"),
            _TransportResponse(
                text="<h1 class='title'>Fallback Product</h1>"
                "<span class='price'>777.00</span>"
            ),
        ]
    )

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=_selector(
                _decision(
                    "cheap_proxy_http",
                    proxy_required=True,
                    proxy_tier="cheap",
                    allow_fallback=True,
                    cost_level="cheap",
                )
            ),
            find_feed_item=lambda tracked_product, *, session: None,
            curl_transport=transport,
            proxy_leaser=lambda source, purpose, job_id, **kwargs: leases.pop(0),
            proxy_reporter=lambda token, status, event_type, response_ms, **kwargs: (
                reports.append((token, status, event_type, response_ms))
            ),
            schema_resolver=_schema,
            now=NOW,
        ),
    )

    assert result.product_name == "Fallback Product"
    assert [call["proxy_url"] for call in transport.calls] == [
        "http://cheap.proxy",
        "http://std.proxy",
    ]
    assert reports == [
        ("lease-cheap", "failed", "http_429", 111),
        ("lease-standard", "success", "success", 111),
    ]
    assert [attempt.strategy for attempt in _attempts(db_session)] == [
        "cheap_proxy_http",
        "standard_proxy_http",
    ]
    assert _attempts(db_session)[0].error_type == "http_429"


def test_free_tariff_does_not_fallback_to_expensive_browser(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        FetchPipelineFailed,
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)
    browser = _FakeBrowserFetcher()

    with pytest.raises(FetchPipelineFailed) as exc_info:
        execute_product_fetch(
            product.id,
            ProductFetchExecutionContext(
                session=db_session,
                user_limits=_limits(browser_fallback_allowed=False),
                strategy_selector=_selector(
                    _decision(
                        "residential_proxy_http",
                        proxy_required=True,
                        proxy_tier="residential",
                        allow_fallback=False,
                        cost_level="expensive",
                    )
                ),
                find_feed_item=lambda tracked_product, *, session: None,
                curl_transport=_FakeCurlTransport([FetchError("http_429")]),
                proxy_leaser=lambda source, purpose, job_id, **kwargs: _Lease(
                    lease_token="lease-res",
                    endpoint=_Endpoint(
                        pool_id=12,
                        id=22,
                        endpoint_ref="http://res.proxy",
                    ),
                ),
                proxy_reporter=lambda *args, **kwargs: None,
                browser_fetcher=browser,
                schema_resolver=_schema,
                now=NOW,
            ),
        )

    assert exc_info.value.attempted_strategies == ["residential_proxy_http"]
    assert browser.calls == []


def test_heavy_browser_strategy_calls_camoufox_fetcher(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session, source="ozon")
    camoufox_calls: list[dict[str, Any]] = []

    def fake_camoufox(url: str, **kwargs: Any) -> BrowserFetchResult:
        camoufox_calls.append({"url": url, **kwargs})
        return BrowserFetchResult(
            final_url=url,
            html="<h1 class='title'>Camoufox Product</h1>"
            "<span class='price'>888.00</span>",
            screenshot_object_key=None,
            response_status=200,
            elapsed_ms=333,
            browser_engine="camoufox",
        )

    result = execute_product_fetch(
        product.id,
        ProductFetchExecutionContext(
            session=db_session,
            strategy_selector=_selector(_decision("camoufox", cost_level="expensive")),
            find_feed_item=lambda tracked_product, *, session: None,
            camoufox_fetcher=fake_camoufox,
            schema_resolver=_schema,
            now=NOW,
        ),
    )

    assert result.product_name == "Camoufox Product"
    assert camoufox_calls == [
        {
            "url": product.canonical_url,
            "proxy_url": None,
            "timeout": 7,
        }
    ]


def test_all_exhausted_raises_typed_failure(db_session: Session) -> None:
    from app.services.multistage_fetch_executor import (
        FetchPipelineFailed,
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)

    with pytest.raises(FetchPipelineFailed) as exc_info:
        execute_product_fetch(
            product.id,
            ProductFetchExecutionContext(
                session=db_session,
                strategy_selector=_selector(
                    _decision(
                        "cheap_proxy_http",
                        proxy_required=True,
                        proxy_tier="cheap",
                        allow_fallback=True,
                    )
                ),
                find_feed_item=lambda tracked_product, *, session: None,
                curl_transport=_FakeCurlTransport(
                    [
                        FetchError("http_429"),
                        FetchError("http_403"),
                        FetchError("http_429"),
                    ]
                ),
                proxy_leaser=lambda source, purpose, job_id, **kwargs: _Lease(
                    lease_token=f"lease-{job_id}-{len(kwargs)}",
                    endpoint=_Endpoint(
                        pool_id=10,
                        id=20,
                        endpoint_ref="http://proxy.local",
                    ),
                ),
                proxy_reporter=lambda *args, **kwargs: None,
                schema_resolver=_schema,
                now=NOW,
            ),
        )

    assert exc_info.value.source_code == "testshop"
    assert exc_info.value.attempted_strategies == [
        "cheap_proxy_http",
        "standard_proxy_http",
        "residential_proxy_http",
    ]
    assert exc_info.value.last_error_type == "http_429"
    assert _attempt_count(db_session) == 3


def test_proxy_report_called_when_proxy_attempt_fails(
    db_session: Session,
) -> None:
    from app.services.multistage_fetch_executor import (
        FetchPipelineFailed,
        ProductFetchExecutionContext,
        execute_product_fetch,
    )

    product = _product(db_session)
    reports: list[tuple[str, str, str, int | None]] = []

    def proxy_reporter(
        token: str,
        status: str,
        event_type: str,
        response_ms: int | None,
        **kwargs: Any,
    ) -> None:
        reports.append((token, status, event_type, response_ms))

    with pytest.raises(FetchPipelineFailed):
        execute_product_fetch(
            product.id,
            ProductFetchExecutionContext(
                session=db_session,
                strategy_selector=_selector(
                    _decision(
                        "cheap_proxy_http",
                        proxy_required=True,
                        proxy_tier="cheap",
                    )
                ),
                find_feed_item=lambda tracked_product, *, session: None,
                curl_transport=_FakeCurlTransport([FetchError("timeout")]),
                proxy_leaser=lambda source, purpose, job_id, **kwargs: _Lease(
                    lease_token="lease-timeout",
                    endpoint=_Endpoint(
                        pool_id=10,
                        id=20,
                        endpoint_ref="http://cheap.proxy",
                    ),
                ),
                proxy_reporter=proxy_reporter,
                schema_resolver=_schema,
                now=NOW,
            ),
        )

    assert reports == [("lease-timeout", "failed", "timeout", None)]
    assert _attempts(db_session)[0].error_type == "timeout"
