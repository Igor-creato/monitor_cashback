from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clients.cashback_api import CashbackAPIClient, CashbackAPIError
from app.db import SessionLocal
from app.models.monitoring import (
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

DEEPLINKABLE_CASHBACK_STATUSES = frozenset({"partner_exact", "partner_estimated"})
UNAVAILABLE_CASHBACK_STATUSES = frozenset({"no_partner", "partner_unknown_product"})


@dataclass(frozen=True)
class DeeplinkUnavailable:
    reason: str


class DeeplinkCreationError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def create_cashback_deeplink(
    tracked_product_id,
    subscription_id,
    event_id=None,
    *,
    session: Session | None = None,
    client: CashbackAPIClient | None = None,
) -> str | DeeplinkUnavailable:
    del event_id
    with _session_scope(session) as active_session:
        tracked_product = active_session.get(TrackedProduct, tracked_product_id)
        if tracked_product is None:
            return DeeplinkUnavailable("tracked_product_not_found")

        subscription = active_session.get(UserProductSubscription, subscription_id)
        if subscription is None:
            return DeeplinkUnavailable("subscription_not_found")
        if subscription.tracked_product_id != tracked_product.id:
            return DeeplinkUnavailable("subscription_product_mismatch")
        if not subscription.is_active:
            return DeeplinkUnavailable("inactive_subscription")

        snapshot = _get_snapshot(active_session, tracked_product.id)
        if snapshot is None:
            return DeeplinkUnavailable("cashback_snapshot_missing")
        if snapshot.cashback_status in UNAVAILABLE_CASHBACK_STATUSES:
            return DeeplinkUnavailable(snapshot.cashback_status)
        if snapshot.cashback_status not in DEEPLINKABLE_CASHBACK_STATUSES:
            return DeeplinkUnavailable("cashback_unavailable")
        if not snapshot.merchant_id:
            return DeeplinkUnavailable("merchant_missing")

        api_client = client or CashbackAPIClient()
        try:
            response = api_client.create_deeplink(
                {
                    "merchant_id": snapshot.merchant_id,
                    "target_url": tracked_product.canonical_url,
                    "click_id": _new_click_id(),
                }
            )
        except CashbackAPIError as exc:
            raise DeeplinkCreationError("cashback_api_unavailable") from exc

        cashback_url = _cashback_url_from_response(response)
        if cashback_url is None:
            raise DeeplinkCreationError("bad_response")
        return cashback_url


def _get_snapshot(
    session: Session,
    tracked_product_id: int,
) -> TrackedProductCashback | None:
    return session.scalar(
        select(TrackedProductCashback).where(
            TrackedProductCashback.tracked_product_id == tracked_product_id
        )
    )


def _new_click_id() -> str:
    return f"pm_{uuid4().hex}"


def _cashback_url_from_response(response: Any) -> str | None:
    if not isinstance(response, dict):
        return None
    cashback_url = response.get("cashback_url")
    if not isinstance(cashback_url, str) or cashback_url == "":
        return None
    return cashback_url


@contextmanager
def _session_scope(session: Session | None):
    if session is not None:
        yield session
        return

    if SessionLocal is None:
        raise ValueError("Database is not configured.")

    with SessionLocal() as owned_session:
        yield owned_session
