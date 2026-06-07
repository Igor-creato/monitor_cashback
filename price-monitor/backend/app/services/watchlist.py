from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.core.product_url_normalizer import (
    UnsupportedSourceError,
    normalize_product_url,
)
from app.models.monitoring import TrackedProduct, UserProductSubscription
from app.schemas.watchlist import WatchlistItemCreate, WatchlistItemPatch


class UnsupportedWatchlistSourceError(ValueError):
    pass


def add_watchlist_item(
    session: Session,
    item: WatchlistItemCreate,
) -> UserProductSubscription:
    try:
        normalized = normalize_product_url(item.product_url)
    except UnsupportedSourceError as exc:
        raise UnsupportedWatchlistSourceError(str(exc)) from exc

    tracked_product = session.scalar(
        select(TrackedProduct).where(
            TrackedProduct.source == normalized.source,
            TrackedProduct.external_product_id == normalized.external_product_id,
            TrackedProduct.region_code == normalized.region_code,
            TrackedProduct.variant_hash == normalized.variant_hash,
        )
    )

    if tracked_product is None:
        tracked_product = TrackedProduct(
            source=normalized.source,
            external_product_id=normalized.external_product_id,
            canonical_url=normalized.canonical_url,
            region_code=normalized.region_code,
            variant_hash=normalized.variant_hash,
        )
        session.add(tracked_product)
        session.flush()

    subscription = session.scalar(
        _subscription_query().where(
            UserProductSubscription.site_id == item.site_id,
            UserProductSubscription.external_user_id == item.external_user_id,
            UserProductSubscription.tracked_product_id == tracked_product.id,
        )
    )

    if subscription is None:
        subscription = UserProductSubscription(
            site_id=item.site_id,
            external_user_id=item.external_user_id,
            tracked_product=tracked_product,
            target_price=item.target_price,
            target_effective_price=item.target_effective_price,
        )
        session.add(subscription)
        session.flush()

    session.commit()
    return subscription


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
        joinedload(UserProductSubscription.tracked_product)
    )
