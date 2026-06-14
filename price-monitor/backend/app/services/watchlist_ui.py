from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.monitoring import PriceHistory, TrackedProduct, UserProductSubscription
from app.schemas.watchlist_ui import (
    WatchlistUiChartSummaryResponse,
    WatchlistUiItemResponse,
    WatchlistUiPaginationResponse,
    WatchlistUiResponse,
)
from app.services.price_chart import current_utc_datetime, summarize_price_history
from app.services.product_cards import build_product_card

CHART_SUMMARY_DAYS = 30


def build_watchlist_ui_response(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    include_chart_summary: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> WatchlistUiResponse:
    total = _count_active_subscriptions(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    subscriptions = _list_active_subscriptions(
        session,
        site_id=site_id,
        external_user_id=external_user_id,
        limit=limit,
        offset=offset,
    )
    history_by_product = (
        _history_by_product_id(session, subscriptions) if include_chart_summary else {}
    )

    return WatchlistUiResponse(
        items=[
            _build_item(
                subscription,
                chart_history=history_by_product.get(
                    subscription.tracked_product_id,
                ),
            )
            for subscription in subscriptions
        ],
        pagination=WatchlistUiPaginationResponse(
            limit=limit,
            offset=offset,
            total=total,
            has_more=offset + len(subscriptions) < total,
        ),
    )


def _count_active_subscriptions(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
) -> int:
    count = session.scalar(
        select(func.count(UserProductSubscription.id)).where(
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
            UserProductSubscription.is_active.is_(True),
        )
    )
    return int(count or 0)


def _list_active_subscriptions(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    limit: int,
    offset: int,
) -> list[UserProductSubscription]:
    statement = (
        select(UserProductSubscription)
        .options(
            joinedload(UserProductSubscription.tracked_product).joinedload(
                TrackedProduct.cashback,
            )
        )
        .where(
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
            UserProductSubscription.is_active.is_(True),
        )
        .order_by(UserProductSubscription.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def _history_by_product_id(
    session: Session,
    subscriptions: list[UserProductSubscription],
) -> dict[int, list[PriceHistory]]:
    product_ids = [subscription.tracked_product_id for subscription in subscriptions]
    if not product_ids:
        return {}

    period_start = current_utc_datetime() - timedelta(days=CHART_SUMMARY_DAYS)
    statement = (
        select(PriceHistory)
        .where(
            PriceHistory.tracked_product_id.in_(product_ids),
            PriceHistory.fetched_at >= period_start,
        )
        .order_by(
            PriceHistory.tracked_product_id.asc(),
            PriceHistory.fetched_at.asc(),
            PriceHistory.id.asc(),
        )
    )
    grouped: dict[int, list[PriceHistory]] = defaultdict(list)
    for point in session.scalars(statement):
        grouped[point.tracked_product_id].append(point)
    return grouped


def _build_item(
    subscription: UserProductSubscription,
    *,
    chart_history: list[PriceHistory] | None,
) -> WatchlistUiItemResponse:
    card = build_product_card(subscription.tracked_product, subscription)
    chart_summary = (
        _build_chart_summary(chart_history) if chart_history is not None else None
    )
    return WatchlistUiItemResponse(
        subscription_id=subscription.id,
        tracked_product_id=subscription.tracked_product_id,
        title=card.title,
        source_display_name=card.source_display_name or card.source,
        image_url=card.image_url,
        current_price=card.last_price,
        currency=card.currency,
        availability=card.availability,
        cashback=card.cashback,
        chart_summary=chart_summary,
    )


def _build_chart_summary(
    history: list[PriceHistory],
) -> WatchlistUiChartSummaryResponse:
    summary, labels = summarize_price_history(history)
    return WatchlistUiChartSummaryResponse(
        trend=summary.trend,
        delta_vs_avg_percent=summary.delta_vs_avg_percent,
        headline=labels.headline,
    )
