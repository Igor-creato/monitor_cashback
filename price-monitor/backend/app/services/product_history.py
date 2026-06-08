from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import PriceHistory, UserProductSubscription


def current_utc_datetime() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def list_product_price_history(
    session: Session,
    *,
    tracked_product_id: int,
    site_id: str,
    external_user_id: str,
    days: int = 30,
) -> list[PriceHistory] | None:
    subscription_id = session.scalar(
        select(UserProductSubscription.id).where(
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
            UserProductSubscription.tracked_product_id == tracked_product_id,
            UserProductSubscription.is_active.is_(True),
        )
    )
    if subscription_id is None:
        return None

    period_start = current_utc_datetime() - timedelta(days=days)
    statement = (
        select(PriceHistory)
        .where(
            PriceHistory.tracked_product_id == tracked_product_id,
            PriceHistory.fetched_at >= period_start,
        )
        .order_by(PriceHistory.fetched_at.asc(), PriceHistory.id.asc())
    )
    return list(session.scalars(statement))
