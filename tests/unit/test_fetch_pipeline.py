from __future__ import annotations

import importlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from tests.conftest import signed_headers

from price_monitor.domains.fetching.ports import FetchPageResult, ProductExtraction
from price_monitor.domains.fetching.service import FetchPipeline
from price_monitor.domains.fetching.sources.base import SourceFetchResult
from price_monitor.domains.pricing.models import PricePoint
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import AlertEvent, FetchAttempt, FetchJob, OutboxEvent
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


class ManagedUnblockerFetcher:
    def __init__(self, *, html: str) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.html = html

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        self.calls.append((url, proxy_url))
        return FetchPageResult(
            content=self.html,
            final_url=url,
            http_status=200,
            response_ms=47,
            provider_name="decodo-web-scraping-api",
            provider_request_id="decodo-task-456",
            rendered=True,
        )


class FakeProxyUrlResolver:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values
        self.calls: list[str] = []

    def resolve(self, *, secret_ref: str) -> str | None:
        self.calls.append(secret_ref)
        return self.values.get(secret_ref)


class LowConfidenceFetcher:
    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        return FetchPageResult(
            content="""
            <meta property="og:title" content="Weak">
            <meta property="product:price:amount" content="1.00">
            <meta property="product:price:currency" content="RUB">
            """,
            final_url=url,
            http_status=200,
            response_ms=5,
        )


def test_fetch_pipeline_updates_product_and_records_price_point_from_direct_fetch(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    direct_fetcher = FakeFetcher(html=_product_html(title="Direct Phone", price="123.45"))
    proxy_fetcher = FakeFetcher(exc=AssertionError("proxy fetcher should not be used"))
    browser_fetcher = FakeFetcher(exc=AssertionError("browser fetcher should not be used"))
    now = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
    job = FetchJob(
        product_id=product.id,
        logical_key="watchlist:item-1:initial:req-fetch-pipeline",
        status="queued",
        scheduled_for=now,
    )
    session.add(job)
    session.flush()

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        proxy_fetcher=proxy_fetcher,
        browser_fetcher=browser_fetcher,
    ).run(product_id=product.id, now=now, fetch_job_id=job.id)

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
    assert attempts[0].fetch_job_id == job.id
    assert attempts[0].status == "ok"
    assert attempts[0].proxy_tier is None
    assert attempts[0].product_data_found is True
    assert attempts[0].error_type is None
    assert attempts[0].parser_version == "generic-html-v1"
    assert attempts[0].parser_confidence == "0.90"
    assert attempts[0].challenge_detected is False
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


def test_fetch_pipeline_records_parser_metadata_and_blocks_low_confidence(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    now = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)

    result = FetchPipeline(session, direct_fetcher=LowConfidenceFetcher()).run(
        product.id,
        now=now,
    )
    attempt = session.query(FetchAttempt).one()

    assert result.status == "low_confidence"
    assert attempt.reason == "low_confidence"
    assert attempt.parser_version == "generic-html-v1"
    assert attempt.parser_confidence == "0.40"
    assert session.query(PricePoint).count() == 0


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


def test_fetch_pipeline_classifies_captcha_challenge_without_price_point(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    direct_fetcher = FakeFetcher(
        html="""
        <script>
        window._config_ = {"action":"captcha","url":"/_____tmd_____/punish?x5secdata=abc"};
        </script>
        """
    )

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
    ).run(product_id=product.id, now=datetime(2026, 7, 2, 10, 0, tzinfo=UTC))

    session.commit()

    refreshed_product = session.get(Product, product.id)
    attempts = session.scalars(
        select(FetchAttempt).where(FetchAttempt.product_id == product.id)
    ).all()
    price_points = session.scalars(
        select(PricePoint).where(PricePoint.product_id == product.id)
    ).all()

    assert result.status == "captcha_detected"
    assert refreshed_product is not None
    assert refreshed_product.last_fetch_status == "captcha_detected"
    assert refreshed_product.current_price_minor is None
    assert len(attempts) == 1
    assert attempts[0].status == "failed"
    assert attempts[0].reason == "captcha_detected"
    assert attempts[0].product_data_found is False
    assert price_points == []


def test_fetch_pipeline_preserves_fetch_failed_when_extraction_finds_no_product_data(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)
    direct_fetcher = FakeFetcher(html="<html><body><div>No product data here</div></body></html>")

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
    ).run(product_id=product.id, now=datetime(2026, 7, 2, 10, 5, tzinfo=UTC))

    session.commit()

    refreshed_product = session.get(Product, product.id)
    attempts = session.scalars(
        select(FetchAttempt).where(FetchAttempt.product_id == product.id)
    ).all()

    assert result.status == "fetch_failed"
    assert refreshed_product is not None
    assert refreshed_product.last_fetch_status == "fetch_failed"
    assert len(attempts) == 1
    assert attempts[0].status == "failed"
    assert attempts[0].reason == "product_data_not_found"
    assert attempts[0].product_data_found is False


def test_fetch_pipeline_records_provider_metadata_on_attempt(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = _create_product(session, browser_fallback_allowed=False)

    class ProviderMetadataAdapter:
        def fetch_product(self, context: object) -> SourceFetchResult:
            del context
            return SourceFetchResult(
                status="ok",
                extraction=ProductExtraction(
                    title="Rendered Phone",
                    price_minor=54321,
                    currency="RUB",
                    image_url="https://example.com/rendered.jpg",
                    rating_value="4.9",
                    availability=None,
                    canonical_url=product.canonical_url,
                    source_product_id="provider-sku-1",
                    parser_version="provider-html-v1",
                    confidence=Decimal("0.95"),
                ),
                http_status=200,
                response_ms=321,
                reason=None,
                block_reason=None,
                challenge_detected=False,
                parser_version="provider-html-v1",
                parser_confidence="0.95",
                provider_name="browser-provider",
                provider_request_id="req-provider-123",
                provider_cost_minor=17,
                rendered=True,
            )

    monkeypatch.setattr(
        "price_monitor.domains.fetching.service.get_adapter_for_source",
        lambda source_domain: ProviderMetadataAdapter(),
    )

    result = FetchPipeline(
        session,
        direct_fetcher=FakeFetcher(html=_product_html(title="ignored", price="1.00")),
    ).run(product_id=product.id, now=datetime(2026, 7, 2, 10, 10, tzinfo=UTC))

    session.commit()

    attempt = session.scalars(
        select(FetchAttempt).where(FetchAttempt.product_id == product.id)
    ).one()

    assert result.status == "ok"
    assert attempt.status == "ok"
    assert attempt.provider_name == "browser-provider"
    assert attempt.provider_request_id == "req-provider-123"
    assert attempt.provider_cost_minor == 17
    assert attempt.rendered is True


def test_fetch_pipeline_preserves_browser_rendered_metadata_with_generic_adapter(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=True)
    direct_fetcher = FakeFetcher(exc=TimeoutError("direct timed out"))
    browser_fetcher = FakeFetcher(
        html="""
        <meta property="og:title" content="Rendered Weak">
        <meta property="product:price:amount" content="1.00">
        <meta property="product:price:currency" content="RUB">
        """
    )

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        browser_fetcher=browser_fetcher,
    ).run(product_id=product.id, now=datetime(2026, 7, 2, 10, 15, tzinfo=UTC))

    session.commit()

    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()

    assert result.status == "low_confidence"
    assert [attempt.strategy for attempt in attempts] == ["direct", "browser"]
    assert attempts[1].reason == "low_confidence"
    assert attempts[1].parser_version == "generic-html-v1"
    assert attempts[1].parser_confidence == "0.40"
    assert attempts[1].rendered is True


def test_fetch_pipeline_clears_stale_reason_on_low_confidence_browser_fallback(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=True)
    direct_fetcher = FakeFetcher(
        html="""
        <script>
        window._config_ = {"action":"captcha","url":"/_____tmd_____/punish?x5secdata=abc"};
        </script>
        """
    )
    browser_fetcher = FakeFetcher(
        html="""
        <meta property="og:title" content="Rendered Weak">
        <meta property="product:price:amount" content="1.00">
        <meta property="product:price:currency" content="RUB">
        """
    )

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        browser_fetcher=browser_fetcher,
    ).run(product_id=product.id, now=datetime(2026, 7, 2, 10, 20, tzinfo=UTC))

    session.commit()

    refreshed_product = session.get(Product, product.id)
    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()

    assert result.status == "low_confidence"
    assert result.reason == "low_confidence"
    assert refreshed_product is not None
    assert refreshed_product.last_fetch_status == "low_confidence"
    assert [attempt.strategy for attempt in attempts] == ["direct", "browser"]
    assert attempts[0].reason == "captcha_detected"
    assert attempts[1].reason == "low_confidence"
    assert attempts[1].parser_version == "generic-html-v1"
    assert attempts[1].parser_confidence == "0.40"


def test_fetch_pipeline_uses_managed_unblocker_after_browser_failure(
    session: Session,
) -> None:
    product = _create_product(session, browser_fallback_allowed=True)
    direct_fetcher = FakeFetcher(exc=TimeoutError("direct timed out"))
    browser_fetcher = FakeFetcher(exc=RuntimeError("browser provider failed"))
    managed_unblocker_fetcher = ManagedUnblockerFetcher(
        html=_product_html(title="Decodo Phone", price="333.44")
    )
    now = datetime(2026, 7, 2, 10, 25, tzinfo=UTC)

    result = FetchPipeline(
        session,
        direct_fetcher=direct_fetcher,
        browser_fetcher=browser_fetcher,
        managed_unblocker_fetcher=managed_unblocker_fetcher,
    ).run(product_id=product.id, now=now)

    session.commit()

    refreshed_product = session.get(Product, product.id)
    attempts = session.scalars(
        select(FetchAttempt)
        .where(FetchAttempt.product_id == product.id)
        .order_by(FetchAttempt.created_at.asc())
    ).all()

    assert result.status == "ok"
    assert refreshed_product is not None
    assert refreshed_product.title == "Decodo Phone"
    assert refreshed_product.current_price_minor == 33344
    assert managed_unblocker_fetcher.calls == [(product.canonical_url, None)]
    assert [attempt.strategy for attempt in attempts] == [
        "direct",
        "browser",
        "managed_unblocker",
    ]
    assert attempts[2].status == "ok"
    assert attempts[2].provider_name == "decodo-web-scraping-api"
    assert attempts[2].provider_request_id == "decodo-task-456"
    assert attempts[2].rendered is True


def test_fetch_product_task_uses_http_fetcher_to_update_product(
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

    class DummyHttpProductPageFetcher(FakeFetcher):
        def __init__(self) -> None:
            super().__init__(html=_product_html(title="Worker Phone", price="222.33"))

    monkeypatch.setattr(
        fetch_product_module,
        "HttpProductPageFetcher",
        DummyHttpProductPageFetcher,
        raising=False,
    )

    result = fetch_product_module.fetch_product(product.id)

    session.expire_all()
    refreshed_product = session.get(Product, product.id)
    attempts = session.scalars(
        select(FetchAttempt).where(FetchAttempt.product_id == product.id)
    ).all()

    assert result == {"product_id": product.id, "status": "ok"}
    assert refreshed_product is not None
    assert refreshed_product.title == "Worker Phone"
    assert refreshed_product.current_price_minor == 22233
    assert refreshed_product.last_fetch_status == "ok"
    assert refreshed_product.last_fetched_at is not None
    assert len(attempts) == 1
    assert attempts[0].strategy == "direct"


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
        def __init__(self) -> None:
            self.job = type(
                "Job",
                (),
                {
                    "status": "queued",
                    "status_reason": "stale",
                    "started_at": None,
                    "finished_at": None,
                    "attempt_count": 0,
                },
            )()

        def __enter__(self) -> DummySession:
            seen["entered"] = True
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            seen["exited"] = True

        def commit(self) -> None:
            seen["committed"] = True

        def flush(self) -> None:
            seen["flushed"] = True

        def get(self, model: object, key: str) -> object:
            seen["job_model"] = model
            seen["job_key"] = key
            seen["job"] = self.job
            return self.job

    class DummyFactory:
        def __call__(self) -> DummySession:
            return DummySession()

    class DummyPipeline:
        def __init__(self, session: object, **kwargs: object) -> None:
            seen["session"] = session
            seen["direct_fetcher"] = kwargs.get("direct_fetcher")
            seen["browser_fetcher"] = kwargs.get("browser_fetcher")
            seen["managed_unblocker_fetcher"] = kwargs.get("managed_unblocker_fetcher")

        def run(self, *, product_id: str, fetch_job_id: str | None = None) -> object:
            seen["product_id"] = product_id
            seen["fetch_job_id"] = fetch_job_id
            return type("Result", (), {"status": "ok"})()

    class DummyHttpProductPageFetcher:
        pass

    class DummyBrowserFetcher:
        pass

    class DummyManagedUnblockerFetcher:
        pass

    dummy_browser_fetcher = DummyBrowserFetcher()
    dummy_managed_unblocker_fetcher = DummyManagedUnblockerFetcher()
    dummy_stored_settings = {
        "joom_browser_provider_url": "",
        "joom_browser_provider_token": "",
        "joom_browser_provider_timeout_seconds": "25.0",
        "joom_browser_provider_wait_selector": 'meta[property="product:price:amount"]',
    }

    class DummySourceService:
        def __init__(self, session: object) -> None:
            seen["source_service_session"] = session

        def get_settings(self) -> dict[str, str]:
            return dummy_stored_settings

    monkeypatch.setattr(fetch_product_module, "get_session_factory", lambda: DummyFactory())
    monkeypatch.setattr(fetch_product_module, "FetchPipeline", DummyPipeline)
    monkeypatch.setattr(fetch_product_module, "SourceService", DummySourceService)
    monkeypatch.setattr(
        fetch_product_module,
        "HttpProductPageFetcher",
        DummyHttpProductPageFetcher,
        raising=False,
    )

    def build_dummy_browser_fetcher(settings: object, stored_settings: object) -> object:
        seen["stored_settings"] = stored_settings
        return dummy_browser_fetcher

    monkeypatch.setattr(
        fetch_product_module,
        "build_source_browser_fetcher",
        build_dummy_browser_fetcher,
        raising=False,
    )
    monkeypatch.setattr(
        fetch_product_module,
        "build_managed_unblocker_fetcher",
        lambda settings: dummy_managed_unblocker_fetcher,
        raising=False,
    )

    result = fetch_product_module.fetch_product("product-123", "job-123")

    assert result == {"product_id": "product-123", "status": "ok"}
    assert seen["entered"] is True
    assert seen["committed"] is True
    assert seen["exited"] is True
    assert seen["product_id"] == "product-123"
    assert seen["fetch_job_id"] == "job-123"
    assert seen["job_key"] == "job-123"
    assert seen["job"].status == "ok"
    assert seen["job"].status_reason is None
    assert seen["job"].started_at is not None
    assert seen["job"].finished_at is not None
    assert seen["job"].attempt_count == 1
    assert seen["source_service_session"] is seen["session"]
    assert isinstance(seen["direct_fetcher"], DummyHttpProductPageFetcher)
    assert seen["browser_fetcher"] is dummy_browser_fetcher
    assert seen["managed_unblocker_fetcher"] is dummy_managed_unblocker_fetcher
    assert seen["stored_settings"] is dummy_stored_settings
    assert seen["stored_settings"]["joom_browser_provider_url"] == ""


def test_fetch_product_task_time_limits_allow_managed_unblocker_latency() -> None:
    fetch_product_module = importlib.import_module("price_monitor.workers.tasks.fetch_product")

    assert fetch_product_module.fetch_product.soft_time_limit == 180
    assert fetch_product_module.fetch_product.time_limit == 210


def test_fetch_product_task_marks_quarantined_pipeline_result_on_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_product_module = importlib.import_module("price_monitor.workers.tasks.fetch_product")
    seen: dict[str, object] = {}

    class DummySession:
        def __init__(self) -> None:
            self.job = type(
                "Job",
                (),
                {
                    "status": "queued",
                    "status_reason": "stale",
                    "started_at": None,
                    "finished_at": None,
                    "attempt_count": 0,
                },
            )()

        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb

        def commit(self) -> None:
            seen["committed"] = True

        def flush(self) -> None:
            seen["flushed"] = True

        def get(self, model: object, key: str) -> object:
            del model
            seen["job_key"] = key
            return self.job

    class DummyFactory:
        def __init__(self) -> None:
            self.last_session: DummySession | None = None

        def __call__(self) -> DummySession:
            self.last_session = DummySession()
            return self.last_session

    class DummyPipeline:
        def __init__(self, session: object, **kwargs: object) -> None:
            del session, kwargs

        def run(self, *, product_id: str, fetch_job_id: str | None = None) -> object:
            del product_id, fetch_job_id
            return type("Result", (), {"status": "quarantined", "reason": None})()

    class DummySourceService:
        def __init__(self, session: object) -> None:
            del session

        def get_settings(self) -> dict[str, str]:
            return {}

    factory = DummyFactory()
    monkeypatch.setattr(fetch_product_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(fetch_product_module, "FetchPipeline", DummyPipeline)
    monkeypatch.setattr(fetch_product_module, "SourceService", DummySourceService)
    monkeypatch.setattr(
        fetch_product_module,
        "build_source_browser_fetcher",
        lambda settings, stored_settings: None,
        raising=False,
    )

    result = fetch_product_module.fetch_product("product-123", "job-123")

    assert result == {"product_id": "product-123", "status": "quarantined"}
    assert factory.last_session is not None
    job = factory.last_session.job
    assert seen["job_key"] == "job-123"
    assert job.status == "quarantined"
    assert job.status_reason == "quarantined"
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.attempt_count == 1
    assert seen["committed"] is True


def test_fetch_product_task_preserves_dead_letter_pipeline_status_on_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_product_module = importlib.import_module("price_monitor.workers.tasks.fetch_product")
    seen: dict[str, object] = {}

    class DummySession:
        def __init__(self) -> None:
            self.job = type(
                "Job",
                (),
                {
                    "status": "queued",
                    "status_reason": "stale",
                    "started_at": None,
                    "finished_at": None,
                    "attempt_count": 0,
                },
            )()

        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb

        def commit(self) -> None:
            seen["committed"] = True

        def flush(self) -> None:
            seen["flushed"] = True

        def get(self, model: object, key: str) -> object:
            del model
            seen["job_key"] = key
            return self.job

    class DummyFactory:
        def __init__(self) -> None:
            self.last_session: DummySession | None = None

        def __call__(self) -> DummySession:
            self.last_session = DummySession()
            return self.last_session

    class DummyPipeline:
        def __init__(self, session: object, **kwargs: object) -> None:
            del session, kwargs

        def run(self, *, product_id: str, fetch_job_id: str | None = None) -> object:
            del product_id, fetch_job_id
            return type("Result", (), {"status": "dead_letter", "reason": None})()

    class DummySourceService:
        def __init__(self, session: object) -> None:
            del session

        def get_settings(self) -> dict[str, str]:
            return {}

    factory = DummyFactory()
    monkeypatch.setattr(fetch_product_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(fetch_product_module, "FetchPipeline", DummyPipeline)
    monkeypatch.setattr(fetch_product_module, "SourceService", DummySourceService)
    monkeypatch.setattr(
        fetch_product_module,
        "build_source_browser_fetcher",
        lambda settings, stored_settings: None,
        raising=False,
    )

    result = fetch_product_module.fetch_product("product-123", "job-123")

    assert result == {"product_id": "product-123", "status": "dead_letter"}
    assert factory.last_session is not None
    job = factory.last_session.job
    assert seen["job_key"] == "job-123"
    assert job.status == "dead_letter"
    assert job.status_reason == "dead_letter"
    assert job.finished_at is not None
    assert job.attempt_count == 1
    assert seen["committed"] is True


def test_fetch_product_task_marks_job_dead_letter_before_reraising_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_product_module = importlib.import_module("price_monitor.workers.tasks.fetch_product")
    seen: dict[str, object] = {}

    class DummySession:
        def __init__(self) -> None:
            self.job = type(
                "Job",
                (),
                {
                    "status": "queued",
                    "status_reason": None,
                    "started_at": None,
                    "finished_at": None,
                    "attempt_count": 0,
                },
            )()

        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb

        def commit(self) -> None:
            seen["committed"] = True

        def flush(self) -> None:
            seen["flushed"] = True

        def get(self, model: object, key: str) -> object:
            del model
            seen["job_key"] = key
            return self.job

    class DummyFactory:
        def __init__(self) -> None:
            self.last_session: DummySession | None = None

        def __call__(self) -> DummySession:
            self.last_session = DummySession()
            return self.last_session

    class ExplodingPipeline:
        def __init__(self, session: object, **kwargs: object) -> None:
            del session, kwargs

        def run(self, *, product_id: str, fetch_job_id: str | None = None) -> object:
            del product_id, fetch_job_id
            raise ValueError("boom")

    class DummySourceService:
        def __init__(self, session: object) -> None:
            del session

        def get_settings(self) -> dict[str, str]:
            return {}

    factory = DummyFactory()
    monkeypatch.setattr(fetch_product_module, "get_session_factory", lambda: factory)
    monkeypatch.setattr(fetch_product_module, "FetchPipeline", ExplodingPipeline)
    monkeypatch.setattr(fetch_product_module, "SourceService", DummySourceService)
    monkeypatch.setattr(
        fetch_product_module,
        "build_source_browser_fetcher",
        lambda settings, stored_settings: None,
        raising=False,
    )

    with pytest.raises(ValueError, match="boom"):
        fetch_product_module.fetch_product("product-123", "job-123")

    assert factory.last_session is not None
    job = factory.last_session.job
    assert seen["job_key"] == "job-123"
    assert job.status == "dead_letter"
    assert job.status_reason == "ValueError"
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.attempt_count == 1
    assert seen["committed"] is True


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
