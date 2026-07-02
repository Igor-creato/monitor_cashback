from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.api.dependencies import get_db_session, verify_wordpress_request
from price_monitor.core.security import VerifiedRequest
from price_monitor.domains.products.models import Product
from price_monitor.domains.reliability.models import FetchAttempt, FetchJob
from price_monitor.domains.sources.models import MonitoredSource

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/{product_id}", response_model=None)
def product_detail(
    product_id: str,
    verified: Annotated[VerifiedRequest, Depends(verify_wordpress_request)],
    session: Annotated[Session, Depends(get_db_session)],
) -> object:
    del verified
    product = session.get(Product, product_id)
    if product is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "product_not_found", "message": "Товар не найден"}},
        )
    source = session.get(MonitoredSource, product.source_domain)
    if source is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": {"code": "source_not_found", "message": "Источник не найден"}},
        )

    latest_job = session.scalar(
        select(FetchJob)
        .where(FetchJob.product_id == product.id)
        .order_by(FetchJob.created_at.desc(), FetchJob.id.desc())
    )
    latest_attempt = None
    latest_status = product.last_fetch_status
    latest_reason = None
    latest_started_at = None
    latest_finished_at = None

    if latest_job is not None:
        latest_status = latest_job.status
        latest_reason = latest_job.status_reason
        latest_started_at = (
            latest_job.started_at.isoformat() if latest_job.started_at is not None else None
        )
        latest_finished_at = (
            latest_job.finished_at.isoformat() if latest_job.finished_at is not None else None
        )
        latest_attempt = session.scalar(
            select(FetchAttempt)
            .where(FetchAttempt.fetch_job_id == latest_job.id)
            .order_by(FetchAttempt.created_at.desc(), FetchAttempt.id.desc())
        )

    return {
        "product": {
            "id": product.id,
            "canonical_url": product.canonical_url,
            "title": product.title,
            "image_url": product.image_url,
            "rating_value": product.rating_value,
            "current_price_minor": product.current_price_minor,
            "currency": product.currency,
            "last_fetch_status": product.last_fetch_status,
        },
        "source": {
            "source_domain": source.source_domain,
            "display_name": source.display_name,
            "logo_url": source.logo_url,
        },
        "actions": {"direct_url": product.canonical_url},
        "latest_fetch": {
            "status": latest_status,
            "reason": latest_reason,
            "strategy": (
                "direct_http"
                if latest_attempt is not None and latest_attempt.strategy == "direct"
                else latest_attempt.strategy
                if latest_attempt is not None
                else None
            ),
            "provider_name": latest_attempt.provider_name if latest_attempt is not None else None,
            "provider_request_id": (
                latest_attempt.provider_request_id if latest_attempt is not None else None
            ),
            "provider_cost_minor": (
                latest_attempt.provider_cost_minor if latest_attempt is not None else None
            ),
            "block_reason": latest_attempt.block_reason if latest_attempt is not None else None,
            "challenge_detected": (
                latest_attempt.challenge_detected if latest_attempt is not None else False
            ),
            "parser_version": latest_attempt.parser_version if latest_attempt is not None else None,
            "parser_confidence": (
                latest_attempt.parser_confidence if latest_attempt is not None else None
            ),
            "started_at": latest_started_at,
            "finished_at": latest_finished_at,
        },
    }
