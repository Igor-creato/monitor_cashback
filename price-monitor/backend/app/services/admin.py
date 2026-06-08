from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.monitoring import (
    FetchJob,
    NotificationEvent,
    SourceConfig,
    SourceHealthEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)
from app.schemas.admin import (
    AdminErrorResponse,
    AdminJobResponse,
    AdminOverviewResponse,
    AdminProductCashbackResponse,
    AdminProductResponse,
    AdminSourcePatch,
    AdminSourceResponse,
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
