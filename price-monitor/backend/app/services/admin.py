from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.monitoring import (
    FetchAttempt,
    FetchJob,
    MarketplaceConnection,
    MarketplaceSessionSecret,
    NotificationEvent,
    ProxyEndpoint,
    ProxyPool,
    SourceConfig,
    SourceHealthEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.schemas.admin import (
    AdminErrorResponse,
    AdminFetchAttemptResponse,
    AdminFetchEconomicsResponse,
    AdminFetchEconomicsSourceCostResponse,
    AdminJobResponse,
    AdminMarketplaceConnectionResponse,
    AdminMarketplaceConnectionsResponse,
    AdminOverviewResponse,
    AdminProductCashbackResponse,
    AdminProductResponse,
    AdminProxyEndpointResponse,
    AdminProxyPoolDetailResponse,
    AdminProxyPoolResponse,
    AdminSourceHealthResponse,
    AdminSourcePatch,
    AdminSourceResponse,
)

ADMIN_PERIOD_LABEL = "24h"
ADMIN_PERIOD = timedelta(hours=24)
ADMIN_PROXY_TIERS = ("cheap", "standard", "residential", "premium")
ADMIN_BROWSER_STRATEGIES = frozenset(
    {"crawl4ai", "playwright", "camoufox", "crawl4ai_browser", "playwright_browser"}
)


def current_utc_datetime() -> datetime:
    return datetime.now(UTC)


def get_admin_overview(session: Session) -> AdminOverviewResponse:
    cutoff = current_utc_datetime() - timedelta(hours=24)
    return AdminOverviewResponse(
        products_total=_count(session, select(func.count(TrackedProduct.id))),
        active_subscriptions_total=_count(
            session,
            select(func.count(UserProductSubscription.id)).where(
                UserProductSubscription.is_active.is_(True)
            ),
        ),
        fetch_jobs_queued=_count(
            session,
            select(func.count(FetchJob.id)).where(FetchJob.status == "queued"),
        ),
        fetch_jobs_failed_24h=_count(
            session,
            select(func.count(FetchJob.id)).where(
                FetchJob.status == "failed",
                FetchJob.finished_at >= cutoff,
            ),
        ),
        cashback_no_partner_total=_cashback_status_count(session, "no_partner"),
        cashback_estimated_total=_cashback_status_count(session, "partner_estimated"),
        cashback_exact_total=_cashback_status_count(session, "partner_exact"),
        notification_events_pending=_count(
            session,
            select(func.count(NotificationEvent.id)).where(
                NotificationEvent.status == "pending"
            ),
        ),
        sources_enabled=_count(
            session,
            select(func.count(SourceConfig.id)).where(SourceConfig.enabled.is_(True)),
        ),
    )


def list_admin_sources(session: Session) -> list[AdminSourceResponse]:
    sources = session.scalars(
        select(SourceConfig).order_by(SourceConfig.source_code.asc())
    )
    return [_serialize_source(source) for source in sources]


def patch_admin_source(
    session: Session,
    source_code: str,
    patch: AdminSourcePatch,
) -> AdminSourceResponse | None:
    source = session.scalar(
        select(SourceConfig).where(SourceConfig.source_code == source_code)
    )
    if source is None:
        return None

    fields_set = patch.model_fields_set
    if "enabled" in fields_set and patch.enabled is not None:
        source.enabled = patch.enabled
    if (
        "min_fetch_interval_minutes" in fields_set
        and patch.min_fetch_interval_minutes is not None
    ):
        source.min_fetch_interval_minutes = patch.min_fetch_interval_minutes
    if (
        "max_failures_before_quarantine" in fields_set
        and patch.max_failures_before_quarantine is not None
    ):
        source.max_failures_before_quarantine = patch.max_failures_before_quarantine
    if (
        "browser_fallback_enabled" in fields_set
        and patch.browser_fallback_enabled is not None
    ):
        source.browser_fallback_enabled = patch.browser_fallback_enabled

    session.commit()
    session.refresh(source)
    return _serialize_source(source)


def list_admin_products(session: Session) -> list[AdminProductResponse]:
    products = session.scalars(
        select(TrackedProduct)
        .options(joinedload(TrackedProduct.cashback))
        .order_by(TrackedProduct.id.asc())
    )
    return [_serialize_product(product, include_cashback=False) for product in products]


def get_admin_product(
    session: Session,
    tracked_product_id: int,
) -> AdminProductResponse | None:
    product = session.scalar(
        select(TrackedProduct)
        .options(joinedload(TrackedProduct.cashback))
        .where(TrackedProduct.id == tracked_product_id)
    )
    if product is None:
        return None
    return _serialize_product(product, include_cashback=True)


def list_admin_jobs(session: Session) -> list[AdminJobResponse]:
    jobs = session.scalars(
        select(FetchJob)
        .options(joinedload(FetchJob.tracked_product))
        .order_by(FetchJob.id.desc())
    )
    return [_serialize_job(job) for job in jobs]


def list_admin_errors(session: Session) -> list[AdminErrorResponse]:
    failed_jobs = session.scalars(
        select(FetchJob)
        .options(joinedload(FetchJob.tracked_product))
        .where(FetchJob.status == "failed")
        .order_by(FetchJob.id.desc())
    )
    failed_notifications = session.scalars(
        select(NotificationEvent)
        .where(NotificationEvent.status == "failed")
        .order_by(NotificationEvent.id.desc())
    )
    source_errors = session.scalars(
        select(SourceHealthEvent)
        .where(SourceHealthEvent.event_type != "success")
        .order_by(SourceHealthEvent.id.desc())
    )

    items: list[AdminErrorResponse] = []
    items.extend(
        AdminErrorResponse(
            error_type="fetch_job_failed",
            record_id=job.id,
            source=job.tracked_product.source,
            tracked_product_id=job.tracked_product_id,
            status=job.status,
            message=job.error_text,
            created_at=job.created_at,
        )
        for job in failed_jobs
    )
    items.extend(
        AdminErrorResponse(
            error_type="notification_event_failed",
            record_id=event.id,
            tracked_product_id=event.tracked_product_id,
            status=event.status,
            message=event.error_text,
            created_at=event.created_at,
        )
        for event in failed_notifications
    )
    items.extend(
        AdminErrorResponse(
            error_type=f"source_health_{event.event_type}",
            record_id=event.id,
            source=event.source_code,
            status=event.event_type,
            message=str(event.status_code) if event.status_code is not None else None,
            created_at=event.created_at,
        )
        for event in source_errors
    )
    return items


def get_admin_fetch_economics(session: Session) -> AdminFetchEconomicsResponse:
    cutoff = _admin_period_cutoff()
    attempts = list(
        session.scalars(
            select(FetchAttempt)
            .where(FetchAttempt.created_at >= cutoff)
            .order_by(FetchAttempt.id.asc())
        )
    )
    pools_by_id = _proxy_pools_by_id(session, attempts)

    total_count = len(attempts)
    success_count = _success_attempt_count(attempts)
    total_cost = _attempt_total_cost(attempts)
    proxy_cost_by_tier = {tier: Decimal("0") for tier in ADMIN_PROXY_TIERS}
    proxy_usage_by_tier = {tier: 0 for tier in ADMIN_PROXY_TIERS}

    for attempt in attempts:
        if attempt.proxy_pool_id is None:
            continue
        pool = pools_by_id.get(attempt.proxy_pool_id)
        if pool is None or pool.tier not in proxy_cost_by_tier:
            continue
        proxy_usage_by_tier[pool.tier] += 1
        proxy_cost_by_tier[pool.tier] += attempt.cost_estimated or Decimal("0")

    return AdminFetchEconomicsResponse(
        period=ADMIN_PERIOD_LABEL,
        cost_per_successful_fetch=_format_decimal(
            _cost_per_success(total_cost, success_count)
        ),
        success_rate=_format_rate_decimal(success_count, total_count),
        browser_fallback_rate=_format_rate_decimal(
            _browser_attempt_count(attempts),
            total_count,
        ),
        http_403_count=_attempt_error_count(attempts, "http_403", 403),
        http_429_count=_attempt_error_count(attempts, "http_429", 429),
        captcha_count=_attempt_captcha_count(attempts),
        proxy_cost_by_tier={
            tier: _format_decimal(proxy_cost_by_tier[tier])
            for tier in ADMIN_PROXY_TIERS
        },
        proxy_usage_by_tier=proxy_usage_by_tier,
        source_costs=_source_costs(attempts),
    )


def list_admin_proxy_pools(session: Session) -> list[AdminProxyPoolResponse]:
    pools = session.scalars(
        select(ProxyPool)
        .options(selectinload(ProxyPool.endpoints))
        .order_by(ProxyPool.id.asc())
    )
    return [_serialize_proxy_pool(pool) for pool in pools]


def get_admin_proxy_pool(
    session: Session,
    pool_id: int,
) -> AdminProxyPoolDetailResponse | None:
    pool = session.scalar(
        select(ProxyPool)
        .options(selectinload(ProxyPool.endpoints))
        .where(ProxyPool.id == pool_id)
    )
    if pool is None:
        return None
    base = _serialize_proxy_pool(pool)
    return AdminProxyPoolDetailResponse(
        **base.model_dump(),
        endpoints=[
            _serialize_proxy_endpoint(endpoint)
            for endpoint in sorted(pool.endpoints, key=lambda item: item.id)
        ],
    )


def get_admin_source_health(
    session: Session,
    source_code: str,
) -> AdminSourceHealthResponse:
    cutoff = _admin_period_cutoff()
    events = list(
        session.scalars(
            select(SourceHealthEvent).where(
                SourceHealthEvent.source_code == source_code,
                SourceHealthEvent.created_at >= cutoff,
            )
        )
    )
    success_count = sum(1 for event in events if event.event_type == "success")
    total_count = len(events)
    failure_count = total_count - success_count

    return AdminSourceHealthResponse(
        source_code=source_code,
        period=ADMIN_PERIOD_LABEL,
        success_count=success_count,
        failure_count=failure_count,
        total_count=total_count,
        success_rate=_format_rate_decimal(success_count, total_count),
        http_403_count=_source_event_count(events, "http_403"),
        http_429_count=_source_event_count(events, "http_429"),
        captcha_count=_source_event_count(events, "captcha_detected"),
        timeout_count=_source_event_count(events, "timeout"),
        parser_error_count=_source_event_count(events, "parser_error"),
        price_not_found_count=_source_event_count(events, "price_not_found"),
        cashback_api_error_count=_source_event_count(events, "cashback_api_error"),
    )


def list_admin_fetch_attempts(
    session: Session,
    *,
    source: str | None = None,
    strategy: str | None = None,
    status: str | None = None,
) -> list[AdminFetchAttemptResponse]:
    statement = select(FetchAttempt)
    if source is not None:
        statement = statement.where(FetchAttempt.source_code == source)
    if strategy is not None:
        statement = statement.where(FetchAttempt.strategy == strategy)
    if status is not None:
        statement = statement.where(FetchAttempt.status == status)

    attempts = session.scalars(statement.order_by(FetchAttempt.id.asc()))
    return [_serialize_fetch_attempt(attempt) for attempt in attempts]


def list_admin_marketplace_connections(
    session: Session,
) -> AdminMarketplaceConnectionsResponse:
    connections = session.scalars(
        select(MarketplaceConnection)
        .options(selectinload(MarketplaceConnection.secrets))
        .order_by(MarketplaceConnection.id.asc())
    )
    return AdminMarketplaceConnectionsResponse(
        items=[
            _serialize_marketplace_connection(connection) for connection in connections
        ]
    )


def _count(session: Session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _cashback_status_count(session: Session, status: str) -> int:
    return _count(
        session,
        select(func.count(TrackedProductCashback.id)).where(
            TrackedProductCashback.cashback_status == status
        ),
    )


def _serialize_source(source: SourceConfig) -> AdminSourceResponse:
    return AdminSourceResponse(
        source_code=source.source_code,
        source_name=source.source_name,
        enabled=source.enabled,
        fetch_strategy=source.fetch_strategy,
        min_fetch_interval_minutes=source.min_fetch_interval_minutes,
        max_failures_before_quarantine=source.max_failures_before_quarantine,
        browser_fallback_enabled=source.browser_fallback_enabled,
    )


def _serialize_product(
    product: TrackedProduct,
    *,
    include_cashback: bool,
) -> AdminProductResponse:
    snapshot = product.cashback
    cashback_status = snapshot.cashback_status if snapshot is not None else "unknown"
    return AdminProductResponse(
        tracked_product_id=product.id,
        source=product.source,
        external_product_id=product.external_product_id,
        canonical_url=product.canonical_url,
        region_code=product.region_code,
        product_name=product.product_name,
        image_url=product.image_url,
        last_price=_format_money(product.last_price),
        last_old_price=_format_money(product.last_old_price),
        currency=product.currency,
        last_availability=product.last_availability,
        last_checked_at=product.last_checked_at,
        last_success_at=product.last_success_at,
        last_status=product.last_status,
        fail_count=product.fail_count,
        cashback_status=cashback_status,
        cashback=_serialize_cashback(snapshot)
        if include_cashback and snapshot
        else None,
    )


def _serialize_cashback(
    snapshot: TrackedProductCashback,
) -> AdminProductCashbackResponse:
    return AdminProductCashbackResponse(
        cashback_status=snapshot.cashback_status,
        merchant_id=snapshot.merchant_id,
        merchant_name=snapshot.merchant_name,
        network=snapshot.network,
        offer_id=snapshot.offer_id,
        user_cashback_exact_rate=_format_rate(snapshot.user_cashback_exact_rate),
        user_cashback_min_rate=_format_rate(snapshot.user_cashback_min_rate),
        user_cashback_max_rate=_format_rate(snapshot.user_cashback_max_rate),
        expected_cashback_exact=_format_money(snapshot.expected_cashback_exact),
        expected_cashback_min=_format_money(snapshot.expected_cashback_min),
        expected_cashback_max=_format_money(snapshot.expected_cashback_max),
        effective_price=_format_money(snapshot.effective_price),
        effective_price_conservative=_format_money(
            snapshot.effective_price_conservative
        ),
        confidence=snapshot.confidence,
        display_policy=snapshot.display_policy,
        message=snapshot.message,
    )


def _serialize_job(job: FetchJob) -> AdminJobResponse:
    return AdminJobResponse(
        job_id=job.id,
        tracked_product_id=job.tracked_product_id,
        source=job.tracked_product.source,
        status=job.status,
        priority=job.priority,
        attempt=job.attempt,
        reason=job.reason,
        next_run_at=job.next_run_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_text=job.error_text,
    )


def _format_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _format_rate(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _admin_period_cutoff() -> datetime:
    return _as_utc_naive(current_utc_datetime() - ADMIN_PERIOD)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _proxy_pools_by_id(
    session: Session,
    attempts: list[FetchAttempt],
) -> dict[int, ProxyPool]:
    pool_ids = {
        attempt.proxy_pool_id
        for attempt in attempts
        if attempt.proxy_pool_id is not None
    }
    if not pool_ids:
        return {}
    pools = session.scalars(select(ProxyPool).where(ProxyPool.id.in_(pool_ids)))
    return {pool.id: pool for pool in pools}


def _success_attempt_count(attempts: list[FetchAttempt]) -> int:
    return sum(1 for attempt in attempts if attempt.status == "success")


def _browser_attempt_count(attempts: list[FetchAttempt]) -> int:
    return sum(
        1 for attempt in attempts if attempt.strategy in ADMIN_BROWSER_STRATEGIES
    )


def _attempt_total_cost(attempts: list[FetchAttempt]) -> Decimal:
    return sum(
        (attempt.cost_estimated or Decimal("0") for attempt in attempts),
        Decimal("0"),
    )


def _cost_per_success(total_cost: Decimal, success_count: int) -> Decimal:
    if success_count == 0:
        return Decimal("0")
    return total_cost / Decimal(success_count)


def _attempt_error_count(
    attempts: list[FetchAttempt],
    error_type: str,
    http_status: int,
) -> int:
    return sum(
        1
        for attempt in attempts
        if attempt.error_type == error_type or attempt.http_status == http_status
    )


def _attempt_captcha_count(attempts: list[FetchAttempt]) -> int:
    return sum(
        1
        for attempt in attempts
        if attempt.error_type in {"captcha", "captcha_detected"}
    )


def _source_costs(
    attempts: list[FetchAttempt],
) -> list[AdminFetchEconomicsSourceCostResponse]:
    grouped: dict[str, list[FetchAttempt]] = {}
    for attempt in attempts:
        grouped.setdefault(attempt.source_code, []).append(attempt)

    items: list[AdminFetchEconomicsSourceCostResponse] = []
    for source_code in sorted(grouped):
        source_attempts = grouped[source_code]
        total_cost = _attempt_total_cost(source_attempts)
        success_count = _success_attempt_count(source_attempts)
        items.append(
            AdminFetchEconomicsSourceCostResponse(
                source_code=source_code,
                total_cost=_format_decimal(total_cost),
                success_count=success_count,
                attempt_count=len(source_attempts),
                cost_per_successful_fetch=_format_decimal(
                    _cost_per_success(total_cost, success_count)
                ),
            )
        )
    return items


def _serialize_proxy_pool(pool: ProxyPool) -> AdminProxyPoolResponse:
    return AdminProxyPoolResponse(
        pool_id=pool.id,
        source=pool.source,
        purpose=pool.purpose,
        enabled=pool.enabled,
        tier=pool.tier,
        cost_per_request=_format_decimal_or_none(pool.cost_per_request, places=8),
        cost_per_gb=_format_decimal_or_none(pool.cost_per_gb, places=8),
        max_cost_per_success=_format_decimal_or_none(
            pool.max_cost_per_success,
            places=8,
        ),
        country_code=pool.country_code,
        region_code=pool.region_code,
        sticky_session_supported=pool.sticky_session_supported,
        priority=pool.priority,
        endpoint_count=len(pool.endpoints),
        enabled_endpoint_count=sum(
            1 for endpoint in pool.endpoints if endpoint.enabled
        ),
        created_at=pool.created_at,
        updated_at=pool.updated_at,
    )


def _serialize_proxy_endpoint(
    endpoint: ProxyEndpoint,
) -> AdminProxyEndpointResponse:
    return AdminProxyEndpointResponse(
        endpoint_id=endpoint.id,
        enabled=endpoint.enabled,
        max_concurrency=endpoint.max_concurrency,
        current_concurrency=endpoint.current_concurrency,
        cooldown_until=endpoint.cooldown_until,
        success_rate_1h=endpoint.success_rate_1h,
        success_rate_24h=endpoint.success_rate_24h,
        avg_response_ms=endpoint.avg_response_ms,
        ban_score=endpoint.ban_score,
        last_403_at=endpoint.last_403_at,
        last_429_at=endpoint.last_429_at,
        last_captcha_at=endpoint.last_captcha_at,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


def _source_event_count(events: list[SourceHealthEvent], event_type: str) -> int:
    return sum(1 for event in events if event.event_type == event_type)


def _serialize_fetch_attempt(attempt: FetchAttempt) -> AdminFetchAttemptResponse:
    return AdminFetchAttemptResponse(
        attempt_id=attempt.id,
        fetch_job_id=attempt.fetch_job_id,
        tracked_product_id=attempt.tracked_product_id,
        source_code=attempt.source_code,
        strategy=attempt.strategy,
        proxy_pool_id=attempt.proxy_pool_id,
        proxy_endpoint_id=attempt.proxy_endpoint_id,
        worker_name=attempt.worker_name,
        status=attempt.status,
        error_type=attempt.error_type,
        http_status=attempt.http_status,
        response_ms=attempt.response_ms,
        cost_estimated=_format_decimal_or_none(attempt.cost_estimated),
        bytes_downloaded=attempt.bytes_downloaded,
        product_data_found=attempt.product_data_found,
        price_found=attempt.price_found,
        image_found=attempt.image_found,
        created_at=attempt.created_at,
    )


def _serialize_marketplace_connection(
    connection: MarketplaceConnection,
) -> AdminMarketplaceConnectionResponse:
    secret = _latest_active_marketplace_secret(connection)
    return AdminMarketplaceConnectionResponse(
        connection_id=connection.id,
        site_id=connection.site_id,
        external_user_id=connection.external_user_id,
        marketplace=connection.marketplace,
        status=connection.status,
        key_version=secret.key_version if secret is not None else None,
        has_secret=secret is not None,
        consent_version=connection.consent_version,
        consented_at=connection.consented_at,
        expires_at=connection.expires_at,
        last_validated_at=connection.last_validated_at,
        last_synced_at=connection.last_synced_at,
        next_retry_at=connection.next_retry_at,
        reconnect_reason=connection.reconnect_reason,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _latest_active_marketplace_secret(
    connection: MarketplaceConnection,
) -> MarketplaceSessionSecret | None:
    active = [secret for secret in connection.secrets if secret.deleted_at is None]
    if not active:
        return None
    return sorted(active, key=lambda item: item.id, reverse=True)[0]


def _format_rate_decimal(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return _format_decimal(Decimal("0"))
    return _format_decimal(Decimal(numerator) / Decimal(denominator))


def _format_decimal(value: Decimal) -> str:
    return f"{value:.6f}"


def _format_decimal_or_none(value: Decimal | None, *, places: int = 6) -> str | None:
    if value is None:
        return None
    return f"{value:.{places}f}"
