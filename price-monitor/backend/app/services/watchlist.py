from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.product_url_normalizer import (
    UnsupportedSourceError,
    normalize_product_url,
)
from app.models.monitoring import TrackedProduct, UserProductSubscription
from app.schemas.watchlist import WatchlistItemCreate, WatchlistItemPatch
from app.services.user_limits import (
    UserLimitsNotFound,
    UserPriceMonitorLimits,
    get_price_monitor_limits,
)
from app.services.user_regions import get_default_user_region

WatchlistAddStatus = Literal["created", "already_exists"]


@dataclass(frozen=True)
class WatchlistAddResult:
    subscription: UserProductSubscription
    status: WatchlistAddStatus


class UnsupportedWatchlistSourceError(ValueError):
    pass


class WatchlistLimitExceededError(ValueError):
    pass


def add_watchlist_item(
    session: Session,
    item: WatchlistItemCreate,
    *,
    limits_provider: Callable[
        [str, str],
        UserPriceMonitorLimits | UserLimitsNotFound,
    ] = get_price_monitor_limits,
) -> WatchlistAddResult:
    try:
        normalized = normalize_product_url(item.product_url)
    except UnsupportedSourceError as exc:
        raise UnsupportedWatchlistSourceError(str(exc)) from exc
    region_code = _region_code_for_watchlist_item(session, item, normalized.region_code)

    tracked_product = session.scalar(
        select(TrackedProduct).where(
            TrackedProduct.source == normalized.source,
            TrackedProduct.external_product_id == normalized.external_product_id,
            TrackedProduct.region_code == region_code,
            TrackedProduct.variant_hash == normalized.variant_hash,
        )
    )

    if tracked_product is not None:
        subscription = session.scalar(
            _subscription_query().where(
                UserProductSubscription.site_id == item.site_id,
                UserProductSubscription.external_user_id == item.external_user_id,
                UserProductSubscription.tracked_product_id == tracked_product.id,
            )
        )
        if subscription is not None:
            return WatchlistAddResult(subscription, "already_exists")

    _ensure_new_subscription_within_limit(session, item, limits_provider)

    if tracked_product is None:
        tracked_product = TrackedProduct(
            source=normalized.source,
            external_product_id=normalized.external_product_id,
            canonical_url=normalized.canonical_url,
            region_code=region_code,
            variant_hash=normalized.variant_hash,
        )
        session.add(tracked_product)
        session.flush()

    subscription = UserProductSubscription(
        site_id=item.site_id,
        external_user_id=item.external_user_id,
        tracked_product=tracked_product,
        region_code=region_code,
        target_price=item.target_price,
        target_effective_price=item.target_effective_price,
    )
    session.add(subscription)
    session.flush()

    session.commit()
    return WatchlistAddResult(subscription, "created")


def list_watchlist_items(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    active_only: bool = True,
    limit: int = 50,
) -> list[UserProductSubscription]:
    statement = (
        _subscription_query()
        .where(
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
        )
        .order_by(UserProductSubscription.id.asc())
        .limit(limit)
    )
    if active_only:
        statement = statement.where(UserProductSubscription.is_active.is_(True))

    return list(session.scalars(statement))


def patch_watchlist_item(
    session: Session,
    *,
    subscription_id: int,
    site_id: str,
    external_user_id: str,
    patch: WatchlistItemPatch,
) -> UserProductSubscription | None:
    subscription = _get_subscription(
        session,
        subscription_id=subscription_id,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    if subscription is None:
        return None

    fields_set = patch.model_fields_set
    if "target_price" in fields_set:
        subscription.target_price = patch.target_price
    if "target_effective_price" in fields_set:
        subscription.target_effective_price = patch.target_effective_price
    if "is_active" in fields_set and patch.is_active is not None:
        subscription.is_active = patch.is_active

    session.commit()
    return subscription


def delete_watchlist_item(
    session: Session,
    *,
    subscription_id: int,
    site_id: str,
    external_user_id: str,
) -> UserProductSubscription | None:
    subscription = _get_subscription(
        session,
        subscription_id=subscription_id,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    if subscription is None:
        return None

    subscription.is_active = False
    session.commit()
    return subscription


def _get_subscription(
    session: Session,
    *,
    subscription_id: int,
    site_id: str,
    external_user_id: str,
) -> UserProductSubscription | None:
    return session.scalar(
        _subscription_query().where(
            UserProductSubscription.id == subscription_id,
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
        )
    )


def _subscription_query() -> Select[tuple[UserProductSubscription]]:
    return select(UserProductSubscription).options(
        joinedload(UserProductSubscription.tracked_product).joinedload(
            TrackedProduct.cashback
        )
    )


def _ensure_new_subscription_within_limit(
    session: Session,
    item: WatchlistItemCreate,
    limits_provider: Callable[
        [str, str],
        UserPriceMonitorLimits | UserLimitsNotFound,
    ],
) -> None:
    user_limits = limits_provider(item.site_id, item.external_user_id)
    if isinstance(user_limits, UserLimitsNotFound):
        raise WatchlistLimitExceededError("max_tracked_products_exceeded")

    active_count = session.scalar(
        select(func.count(UserProductSubscription.id)).where(
            UserProductSubscription.site_id == item.site_id,
            UserProductSubscription.external_user_id == item.external_user_id,
            UserProductSubscription.is_active.is_(True),
        )
    )
    if int(active_count or 0) >= user_limits.limits.max_tracked_products:
        raise WatchlistLimitExceededError("max_tracked_products_exceeded")


def _region_code_for_watchlist_item(
    session: Session,
    item: WatchlistItemCreate,
    normalized_region_code: str,
) -> str:
    explicit_url_region = _explicit_region_from_url(item.product_url)
    if explicit_url_region is not None:
        return explicit_url_region
    if "region_code" in item.model_fields_set:
        return item.region_code
    default_region = get_default_user_region(
        session,
        site_id=item.site_id,
        external_user_id=item.external_user_id,
    )
    return default_region.region_code or normalized_region_code or "default"


def _explicit_region_from_url(url: str) -> str | None:
    query_pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    for key, value in query_pairs:
        if key == "region" and value:
            return value
    return None
