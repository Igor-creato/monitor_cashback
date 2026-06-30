from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import signed_headers

from price_monitor.domains.fetching.ports import FetchPageResult
from price_monitor.domains.fetching.service import FetchPipeline
from price_monitor.domains.pricing.models import PricePoint
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import AlertEvent, FetchAttempt, OutboxEvent
from price_monitor.domains.sources.models import ProxyEndpoint, ProxyPool
from price_monitor.domains.sources.service import MonitoredSourceInput, SourceService
from price_monitor.domains.watchlist.service import WatchlistService


class FakeFetcher:
    def __init__(self, *, html: str | None = None, exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.html = html
        self.exc = exc

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        self.calls.append((url, proxy_url))
        if self.exc is not None:
            raise self.exc
        assert self.html is not None
        return FetchPageResult(content=self.html, final_url=url, http_status=200, response_ms=7)


class FakeProxyUrlResolver:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values
        self.calls: list[str] = []

    def resolve(self, *, secret_ref: str) -> str | None:
        self.calls.append(secret_ref)
        return self.values.get(secret_ref)


def test_fetch_pipeline_updates_product_and_records_price_point_from_direct_fetch(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    direct_fetcher = FakeFetcher(html=_product_html(title="Direct Phone", price="123.45"))
    proxy_fetcher = FakeFetcher(exc=AssertionError("proxy fetcher should not be used"))
    browser_fetcher = FakeFetcher(exc=AssertionError("browser fetcher should not be used"))
    now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        proxy_fetcher=proxy_fetcher,
        browser_fetcher=browser_fetcher,
    ).run(product_id=product.id, now=now)

    session.commit()

    assert result.status == "ok"
    assert direct_fetcher.calls == [(product.canonical_url, None)]

    refreshed_product = session.get(Product, product.id)
    assert refreshed_product is not None
    assert refreshed_product.title == "Direct Phone"
    assert refreshed_product.image_url == "https://example.com/image.jpg"
    assert refreshed_product.rating_value == "4.8"
    assert refreshed_product.current_price_minor == 12345
    assert refreshed_product.currency == "RUB"
    assert refreshed_product.last_fetch_status == "ok"
    assert refreshed_product.last_fetched_at == now

    price_points = session.scalars(
        select(PricePoint).where(PricePoint.product_id == product.id)
    ).all()
    assert len(price_points) == 1
    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()
    assert len(attempts) == 1
    assert attempts[0].strategy == "direct"
    assert attempts[0].status == "ok"
    assert attempts[0].proxy_tier is None
    assert attempts[0].product_data_found is True
    assert attempts[0].error_type is None
    assert price_points[0].fetch_attempt_id == attempts[0].id


def test_fetch_pipeline_does_not_resolve_proxy_before_direct_success(
    session: Session,
) -> None:
    secret_ref = "proxy-ref-tier-1"  # noqa: S105
    proxy_pool = ProxyPool(name="Pool Direct First", status="active")
    session.add(proxy_pool)
    session.flush()
    session.add(
        ProxyEndpoint(
            pool_id=proxy_pool.id,
            tier=1,
            proxy_url_secret_ref=secret_ref,
            status="active",
        )
    )
    product = _create_product(
        session,
        browser_fallback_allowed=False,
        proxy_pool_id=proxy_pool.id,
    )
    direct_fetcher = FakeFetcher(html=_product_html(title="Direct Wins", price="99.90"))
    proxy_fetcher = FakeFetcher(exc=AssertionError("proxy fetcher should not be used"))

    class RaisingProxyUrlResolver:
        def resolve(self, *, secret_ref: str) -> str | None:
            raise AssertionError(f"resolver should not be called: {secret_ref}")

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        proxy_fetcher=proxy_fetcher,
        proxy_url_resolver=RaisingProxyUrlResolver(),
    ).run(product_id=product.id, now=datetime(2026, 6, 30, 11, 0, tzinfo=UTC))

    session.commit()

    assert result.status == "ok"
    assert direct_fetcher.calls == [(product.canonical_url, None)]
    assert proxy_fetcher.calls == []
    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()
    assert len(attempts) == 1
    assert attempts[0].strategy == "direct"
    assert attempts[0].status == "ok"


def test_fetch_pipeline_creates_pending_alert_event_when_price_crosses_target(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    direct_fetcher = FakeFetcher(html=_product_html(title="Alert Phone", price="99.90"))
    proxy_fetcher = FakeFetcher(exc=AssertionError("proxy fetcher should not be used"))
    browser_fetcher = FakeFetcher(exc=AssertionError("browser fetcher should not be used"))

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        proxy_fetcher=proxy_fetcher,
        browser_fetcher=browser_fetcher,
    ).run(product_id=product.id, now=datetime(2026, 6, 30, 11, 30, tzinfo=UTC))

    session.commit()

    assert result.status == "ok"
    alerts = session.scalars(select(AlertEvent)).all()
    assert len(alerts) == 1
    assert alerts[0].status == "pending"
    outbox_events = session.scalars(
        select(OutboxEvent).where(OutboxEvent.event_type == "notification.price_target_reached")
    ).all()
    assert len(outbox_events) == 1


def test_fetch_pipeline_uses_proxy_tier_after_direct_failure_and_redacts_proxy_url(
    session: Session,
) -> None:
    secret_ref = "proxy-ref-tier-1"  # noqa: S105
    proxy_pool = ProxyPool(name="Pool A", status="active")
    session.add(proxy_pool)
    session.flush()
    session.add(
        ProxyEndpoint(
            pool_id=proxy_pool.id,
            tier=1,
            proxy_url_secret_ref=secret_ref,
            status="active",
        )
    )
    product = _create_product(
        session,
        browser_fallback_allowed=False,
        proxy_pool_id=proxy_pool.id,
    )
    direct_fetcher = FakeFetcher(exc=TimeoutError("direct timed out"))
    proxy_fetcher = FakeFetcher(html=_product_html(title="Proxy Phone", price="111.00"))
    browser_fetcher = FakeFetcher(exc=AssertionError("browser fetcher should not be used"))
    proxy_url_resolver = FakeProxyUrlResolver({secret_ref: "http://proxy-tier-1.local"})

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        proxy_fetcher=proxy_fetcher,
        browser_fetcher=browser_fetcher,
        proxy_url_resolver=proxy_url_resolver,
    ).run(product_id=product.id, now=datetime(2026, 6, 30, 12, 0, tzinfo=UTC))

    session.commit()

    assert result.status == "ok"
    assert direct_fetcher.calls == [(product.canonical_url, None)]
    assert proxy_fetcher.calls == [(product.canonical_url, "http://proxy-tier-1.local")]
    assert proxy_url_resolver.calls == [secret_ref]
    assert all(call[1] != secret_ref for call in proxy_fetcher.calls)

    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()
    assert len(attempts) == 2
    assert attempts[0].strategy == "direct"
    assert attempts[0].status == "failed"
    assert attempts[0].error_type == "TimeoutError"
    assert attempts[0].proxy_tier is None
    assert attempts[1].strategy == "proxy"
    assert attempts[1].status == "ok"
    assert attempts[1].proxy_tier == 1


def test_fetch_pipeline_skips_browser_fallback_when_source_disallows_it(
    session: Session,
) -> None:
    secret_ref = "proxy-ref-tier-1"  # noqa: S105
    proxy_pool = ProxyPool(name="Pool B", status="active")
    session.add(proxy_pool)
    session.flush()
    session.add(
        ProxyEndpoint(
            pool_id=proxy_pool.id,
            tier=1,
            proxy_url_secret_ref=secret_ref,
            status="active",
        )
    )
    product = _create_product(
        session,
        browser_fallback_allowed=False,
        proxy_pool_id=proxy_pool.id,
    )
    direct_fetcher = FakeFetcher(exc=TimeoutError("direct timed out"))
    proxy_fetcher = FakeFetcher(exc=RuntimeError("proxy failed"))
    browser_fetcher = FakeFetcher(html=_product_html(title="Browser Phone", price="77.70"))
    proxy_url_resolver = FakeProxyUrlResolver({secret_ref: "http://proxy-tier-1.local"})

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        proxy_fetcher=proxy_fetcher,
        browser_fetcher=browser_fetcher,
        proxy_url_resolver=proxy_url_resolver,
    ).run(product_id=product.id, now=datetime(2026, 6, 30, 13, 0, tzinfo=UTC))

    session.commit()

    assert result.status == "fetch_failed"
    assert browser_fetcher.calls == []
    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()
    assert [attempt.strategy for attempt in attempts] == ["direct", "proxy"]
    assert attempts[1].proxy_tier == 1
    assert attempts[1].error_type == "RuntimeError"


def test_fetch_product_task_without_configured_adapters_returns_not_configured_without_failed_state(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    fetch_product_module = importlib.import_module("price_monitor.workers.tasks.fetch_product")

    class SessionContext:
        def __enter__(self) -> Session:
            return session

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb

    class DummyFactory:
        def __call__(self) -> SessionContext:
            return SessionContext()

    monkeypatch.setattr(fetch_product_module, "get_session_factory", lambda: DummyFactory())

    result = fetch_product_module.fetch_product(product.id)

    session.expire_all()
    refreshed_product = session.get(Product, product.id)
    attempts = session.scalars(
        select(FetchAttempt).where(FetchAttempt.product_id == product.id)
    ).all()

    assert result == {"product_id": product.id, "status": "not_configured"}
    assert refreshed_product is not None
    assert refreshed_product.last_fetch_status is None
    assert refreshed_product.last_fetched_at is None
    assert attempts == []


def test_price_chart_endpoint_requires_hmac_and_returns_daily_summary(
    client: TestClient,
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    session.add_all(
        [
            PricePoint(
                product_id=product.id,
                source_domain=product.source_domain,
                price_minor=12345,
                currency="RUB",
                observed_at=datetime(2026, 6, 30, 10, 0, tzinfo=UTC),
            ),
            PricePoint(
                product_id=product.id,
                source_domain=product.source_domain,
                price_minor=12000,
                currency="RUB",
                observed_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            ),
            PricePoint(
                product_id=product.id,
                source_domain=product.source_domain,
                price_minor=13000,
                currency="RUB",
                observed_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
            ),
        ]
    )
    session.commit()

    history_path = f"/api/v1/products/{product.id}/price-history"
    unsigned_history = client.get(history_path)
    assert unsigned_history.status_code == 401
    assert unsigned_history.json()["error"]["code"] == "authentication_failed"

    chart_path = f"/api/v1/products/{product.id}/price-chart?days=7"
    response = client.get(
        chart_path,
        headers=signed_headers(
            "GET",
            chart_path,
            b"",
            request_id="req-chart",
            idempotency_key=None,
        ),
    )

    assert response.status_code == 200
    assert response.json() == {
        "product_id": product.id,
        "currency": "RUB",
        "points": [
            {"date": "2026-06-29", "min_price_minor": 13000, "max_price_minor": 13000},
            {"date": "2026-06-30", "min_price_minor": 12000, "max_price_minor": 12345},
        ],
        "summary": {"lowest_price_minor": 12000, "latest_price_minor": 12000},
    }


def test_fetch_product_task_runs_pipeline_and_returns_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_product_module = importlib.import_module("price_monitor.workers.tasks.fetch_product")
    seen: dict[str, object] = {}

    class DummySession:
        def __enter__(self) -> DummySession:
            seen["entered"] = True
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            seen["exited"] = True

        def commit(self) -> None:
            seen["committed"] = True

    class DummyFactory:
        def __call__(self) -> DummySession:
            return DummySession()

    class DummyPipeline:
        def __init__(self, session: object) -> None:
            seen["session"] = session

        def run(self, *, product_id: str) -> object:
            seen["product_id"] = product_id
            return type("Result", (), {"status": "ok"})()

    monkeypatch.setattr(fetch_product_module, "get_session_factory", lambda: DummyFactory())
    monkeypatch.setattr(fetch_product_module, "FetchPipeline", DummyPipeline)

    result = fetch_product_module.fetch_product("product-123")

    assert result == {"product_id": "product-123", "status": "ok"}
    assert seen["entered"] is True
    assert seen["committed"] is True
    assert seen["exited"] is True
    assert seen["product_id"] == "product-123"


def _create_product(
    session: Session,
    *,
    browser_fallback_allowed: bool,
    proxy_pool_id: str | None = None,
) -> Product:
    source = SourceService(session).upsert_source(
        MonitoredSourceInput(
            source_domain="example.com",
            display_name="Example",
            logo_url="https://example.com/logo.png",
            status="active",
            fetch_interval_hours=6,
            history_retention_days=90,
            browser_fallback_allowed=browser_fallback_allowed,
            proxy_pool_id=proxy_pool_id,
        )
    )
    result = WatchlistService(session).add_item(
        user_id=f"wp:savello.test:{datetime.now(UTC).timestamp()}",
        product_url="https://example.com/item?id=42",
        target_price_minor=10_000,
        currency="RUB",
        request_id="req-create-product",
        max_tracked_products=10,
    )
    assert result.item is not None
    session.flush()
    product = result.item.product
    assert product is not None
    assert product.source_domain == source.source_domain
    return product


def _product_html(*, title: str, price: str) -> str:
    return f"""
    <html><head>
    <script type="application/ld+json">
    {{"@type":"Product","name":"{title}","image":"https://example.com/image.jpg","aggregateRating":{{"ratingValue":"4.8"}},"offers":{{"price":"{price}","priceCurrency":"RUB"}}}}
    </script>
    </head><body></body></html>
    """
