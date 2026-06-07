from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.cashback_api import CashbackAPIClient, CashbackAPIError
from app.db import SessionLocal
from app.models.monitoring import TrackedProduct, TrackedProductCashback
from app.services.cashback_calculation import normalize_cashback_resolution

logger = logging.getLogger(__name__)


SNAPSHOT_FIELDS = (
    "cashback_status",
    "merchant_id",
    "merchant_name",
    "network",
    "offer_id",
    "rate_id",
    "commission_rate_type",
    "commission_exact",
    "commission_min",
    "commission_max",
    "user_share",
    "user_cashback_exact_rate",
    "user_cashback_min_rate",
    "user_cashback_max_rate",
    "expected_cashback_exact",
    "expected_cashback_min",
    "expected_cashback_max",
    "effective_price",
    "effective_price_conservative",
    "confidence",
    "display_policy",
    "message",
)
DECIMAL_SNAPSHOT_FIELDS = frozenset(
    {
        "commission_exact",
        "commission_min",
        "commission_max",
        "user_share",
        "user_cashback_exact_rate",
        "user_cashback_min_rate",
        "user_cashback_max_rate",
        "expected_cashback_exact",
        "expected_cashback_min",
        "expected_cashback_max",
        "effective_price",
        "effective_price_conservative",
    }
)


def resolve_and_store_product_cashback(
    tracked_product_id,
    price=None,
    currency=None,
    region_code=None,
    *,
    session: Session | None = None,
    client: CashbackAPIClient | None = None,
) -> TrackedProductCashback:
    with _session_scope(session) as active_session:
        tracked_product = active_session.get(TrackedProduct, tracked_product_id)
        if tracked_product is None:
            raise ValueError("Tracked product was not found.")

        resolve_price = _resolve_price(price, tracked_product)
        payload = _resolve_product_payload(
            tracked_product,
            price=resolve_price,
            currency=currency,
            region_code=region_code,
        )
        api_client = client or CashbackAPIClient()

        try:
            response = api_client.resolve_product(payload)
        except CashbackAPIError:
            logger.warning(
                "cashback_api_resolution_failed",
                extra={
                    "failure_type": "cashback_api_unavailable",
                    "tracked_product_id": tracked_product_id,
                },
                exc_info=True,
            )
            existing_snapshot = _get_snapshot(active_session, tracked_product_id)
            if existing_snapshot is not None:
                return existing_snapshot

            return upsert_product_cashback_snapshot(
                tracked_product_id,
                _unknown_requires_check_resolution(),
                session=active_session,
            )

        normalized = normalize_cashback_resolution(response, resolve_price)
        return upsert_product_cashback_snapshot(
            tracked_product_id,
            normalized,
            session=active_session,
        )


def upsert_product_cashback_snapshot(
    tracked_product_id,
    normalized_resolution,
    *,
    session: Session | None = None,
) -> TrackedProductCashback:
    with _session_scope(session) as active_session:
        snapshot = _get_snapshot(active_session, tracked_product_id)
        if snapshot is None:
            snapshot = TrackedProductCashback(
                tracked_product_id=tracked_product_id,
                cashback_status=normalized_resolution["cashback_status"],
                confidence=normalized_resolution["confidence"],
                display_policy=normalized_resolution["display_policy"],
            )
            active_session.add(snapshot)

        for field in SNAPSHOT_FIELDS:
            if field in normalized_resolution:
                setattr(
                    snapshot,
                    field,
                    _snapshot_field_value(field, normalized_resolution[field]),
                )

        snapshot.raw_response_json = _compact_json(normalized_resolution)
        snapshot.checked_at = datetime.now(UTC)
        active_session.commit()
        active_session.refresh(snapshot)
        return snapshot


def _resolve_product_payload(
    tracked_product: TrackedProduct,
    *,
    price: Decimal,
    currency: str | None,
    region_code: str | None,
) -> dict[str, Any]:
    return {
        "url": tracked_product.canonical_url,
        "canonical_url": tracked_product.canonical_url,
        "source": tracked_product.source,
        "external_product_id": tracked_product.external_product_id,
        "price": str(price),
        "currency": currency if currency is not None else tracked_product.currency,
        "region": (
            region_code if region_code is not None else tracked_product.region_code
        ),
    }


def _resolve_price(price: Any, tracked_product: TrackedProduct) -> Decimal:
    resolved_price = price if price is not None else tracked_product.last_price
    if resolved_price is None:
        raise ValueError("Price is required to resolve product cashback.")
    return Decimal(str(resolved_price))


def _unknown_requires_check_resolution() -> dict[str, Any]:
    return {
        "cashback_status": "partner_unknown_product",
        "confidence": "none",
        "display_policy": "cashback_unknown_requires_check",
        "message": "cashback API unavailable; requires check",
    }


def _get_snapshot(
    session: Session,
    tracked_product_id: int,
) -> TrackedProductCashback | None:
    return session.scalar(
        select(TrackedProductCashback).where(
            TrackedProductCashback.tracked_product_id == tracked_product_id
        )
    )


def _snapshot_field_value(field: str, value: Any) -> Any:
    if field not in DECIMAL_SNAPSHOT_FIELDS:
        return value
    return _decimal_or_none(value)


def _decimal_or_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    return value


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


@contextmanager
def _session_scope(session: Session | None):
    if session is not None:
        yield session
        return

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        yield owned_session
