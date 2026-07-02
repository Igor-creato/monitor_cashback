from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.domains.fetching.ports import ProductPageFetcher, ProxyUrlResolver
from price_monitor.domains.fetching.sources.base import FetchContext
from price_monitor.domains.fetching.sources.registry import get_adapter_for_source
from price_monitor.domains.notifications.service import NotificationService
from price_monitor.domains.pricing.models import PricePoint
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import FetchAttempt
from price_monitor.domains.sources.models import MonitoredSource, ProxyEndpoint, ProxyPool

MINIMUM_PARSER_CONFIDENCE = Decimal("0.70")


@dataclass(frozen=True)
class ProductFetchResult:
    product_id: str
    status: str
    reason: str | None = None
    price_point_id: str | None = None
    fetch_attempt_id: str | None = None


class FetchPipeline:
    def __init__(
        self,
        session: Session,
        *,
        direct_fetcher: ProductPageFetcher | None = None,
        proxy_fetcher: ProductPageFetcher | None = None,
        browser_fetcher: ProductPageFetcher | None = None,
        proxy_url_resolver: ProxyUrlResolver | None = None,
    ) -> None:
        self._session = session
        self._direct_fetcher = direct_fetcher
        self._proxy_fetcher = proxy_fetcher
        self._browser_fetcher = browser_fetcher
        self._proxy_url_resolver = proxy_url_resolver

    def run(
        self,
        product_id: str,
        now: datetime | None = None,
        fetch_job_id: str | None = None,
    ) -> ProductFetchResult:
        current_time = now or datetime.now(UTC)
        product = self._session.get(Product, product_id)
        if product is None:
            return ProductFetchResult(product_id=product_id, status="product_not_found")

        source = self._session.get(MonitoredSource, product.source_domain)
        if source is None or source.status != "active":
            product.last_fetch_status = "unsupported_store"
            product.last_fetched_at = current_time
            product.updated_at = current_time
            self._session.flush()
            return ProductFetchResult(product_id=product.id, status="unsupported_store")

        fallback_currency = product.currency or "RUB"
        adapter = get_adapter_for_source(product.source_domain)
        strategies: list[tuple[str, int | None, str | None, ProductPageFetcher]] = []
        if self._direct_fetcher is not None:
            strategies.append(("direct", None, None, self._direct_fetcher))
        strategies.extend(self._proxy_strategies(source))
        if source.browser_fallback_allowed and self._browser_fetcher is not None:
            strategies.append(("browser", None, None, self._browser_fetcher))
        if not strategies:
            return ProductFetchResult(product_id=product.id, status="not_configured")

        terminal_status = "fetch_failed"
        terminal_reason: str | None = None
        for attempt_index, (strategy, proxy_tier, proxy_secret_ref, fetcher) in enumerate(
            strategies
        ):
            attempt_time = current_time + timedelta(microseconds=attempt_index)
            attempt = FetchAttempt(
                fetch_job_id=fetch_job_id,
                product_id=product.id,
                strategy=strategy,
                proxy_tier=proxy_tier,
                status="failed",
                rendered=strategy == "browser",
                challenge_detected=False,
                product_data_found=False,
                created_at=attempt_time,
            )
            self._session.add(attempt)
            try:
                proxy_url = None
                if strategy == "proxy":
                    proxy_url = self._resolve_proxy_url(secret_ref=proxy_secret_ref)
                    if not proxy_url:
                        attempt.reason = "proxy_url_unavailable"
                        self._session.flush()
                        continue
                result = adapter.fetch_product(
                    FetchContext(
                        canonical_url=product.canonical_url,
                        source_domain=product.source_domain,
                        source_product_id=product.source_product_id,
                        strategy=strategy,
                        fetcher=fetcher,
                        proxy_url=proxy_url if strategy == "proxy" else None,
                        fallback_currency=fallback_currency,
                    )
                )
            except Exception as exc:
                attempt.error_type = type(exc).__name__
                attempt.reason = "fetch_error"
                self._session.flush()
                continue

            attempt.http_status = result.http_status
            attempt.response_ms = result.response_ms
            attempt.provider_name = result.provider_name
            attempt.provider_request_id = result.provider_request_id
            attempt.provider_cost_minor = result.provider_cost_minor
            attempt.rendered = attempt.rendered or result.rendered
            attempt.block_reason = result.block_reason
            attempt.challenge_detected = result.challenge_detected
            attempt.parser_version = result.parser_version
            attempt.parser_confidence = result.parser_confidence
            if result.status != "ok" or result.extraction is None:
                attempt.reason = result.reason or result.status
                terminal_reason = attempt.reason
                if attempt.reason != "product_data_not_found":
                    terminal_status = attempt.reason or "fetch_failed"
                self._session.flush()
                continue

            extracted = result.extraction
            attempt.product_data_found = True
            if extracted.confidence < MINIMUM_PARSER_CONFIDENCE:
                attempt.reason = "low_confidence"
                terminal_status = "low_confidence"
                self._session.flush()
                continue

            attempt.status = "ok"
            attempt.reason = None

            product.title = extracted.title
            product.image_url = extracted.image_url
            product.rating_value = extracted.rating_value
            product.current_price_minor = extracted.price_minor
            product.currency = extracted.currency
            product.source_product_id = extracted.source_product_id
            product.last_fetch_status = "ok"
            product.last_fetched_at = current_time
            product.updated_at = current_time

            self._session.flush()

            price_point = PricePoint(
                product_id=product.id,
                fetch_attempt_id=attempt.id,
                source_domain=product.source_domain,
                price_minor=extracted.price_minor,
                currency=extracted.currency,
                observed_at=current_time,
            )
            self._session.add(price_point)
            self._session.flush()
            NotificationService(self._session).evaluate_product(
                product_id=product.id,
                now=current_time,
            )
            return ProductFetchResult(
                product_id=product.id,
                status="ok",
                reason=None,
                price_point_id=price_point.id,
                fetch_attempt_id=attempt.id,
            )

        product.last_fetch_status = terminal_status
        product.last_fetched_at = current_time
        product.updated_at = current_time
        self._session.flush()
        return ProductFetchResult(
            product_id=product.id,
            status=terminal_status,
            reason=terminal_reason,
        )

    def _proxy_strategies(
        self,
        source: MonitoredSource,
    ) -> list[tuple[str, int | None, str | None, ProductPageFetcher]]:
        if self._proxy_fetcher is None or self._proxy_url_resolver is None:
            return []

        strategies: list[tuple[str, int | None, str | None, ProductPageFetcher]] = []
        for endpoint in self._active_proxy_endpoints(source):
            strategies.append(
                ("proxy", endpoint.tier, endpoint.proxy_url_secret_ref, self._proxy_fetcher)
            )
        return strategies

    def _resolve_proxy_url(self, *, secret_ref: str | None) -> str | None:
        if self._proxy_url_resolver is None or not secret_ref:
            return None
        return self._proxy_url_resolver.resolve(secret_ref=secret_ref)

    def _active_proxy_endpoints(self, source: MonitoredSource) -> list[ProxyEndpoint]:
        if not source.proxy_pool_id:
            return []

        pool = self._session.get(ProxyPool, source.proxy_pool_id)
        if pool is None or pool.status != "active":
            return []

        return list(
            self._session.scalars(
                select(ProxyEndpoint)
                .where(
                    ProxyEndpoint.pool_id == source.proxy_pool_id,
                    ProxyEndpoint.status == "active",
                )
                .order_by(ProxyEndpoint.tier.asc(), ProxyEndpoint.id.asc())
            ).all()
        )


def summarize_price_chart(
    points: Sequence[PricePoint],
    *,
    days: int,
) -> tuple[list[dict[str, object]], dict[str, int | None], str | None]:
    if not points:
        return [], {"lowest_price_minor": None, "latest_price_minor": None}, None

    latest_date = points[-1].observed_at.date()
    cutoff_date = latest_date - timedelta(days=days - 1)
    filtered = [point for point in points if point.observed_at.date() >= cutoff_date]
    buckets: dict[date, list[int]] = {}
    for point in filtered:
        point_date = point.observed_at.date()
        buckets.setdefault(point_date, []).append(point.price_minor)

    chart_points = [
        {
            "date": point_date.isoformat(),
            "min_price_minor": min(values),
            "max_price_minor": max(values),
        }
        for point_date, values in sorted(buckets.items())
    ]
    latest_price_minor = filtered[-1].price_minor if filtered else None
    lowest_price_minor = min(point.price_minor for point in filtered) if filtered else None
    currency = filtered[-1].currency if filtered else None
    return (
        chart_points,
        {
            "lowest_price_minor": lowest_price_minor,
            "latest_price_minor": latest_price_minor,
        },
        currency,
    )
