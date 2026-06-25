import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.product_url_normalizer import (
    NormalizedProductUrl,
    UnsupportedSourceError,
    normalize_product_url,
)
from app.models.monitoring import (
    Store,
    StoreSource,
    TrackedProduct,
    UserProductSubscription,
)
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
        normalized = _normalize_watchlist_product_url(session, item.product_url)
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
            if not subscription.is_active:
                _ensure_new_subscription_within_limit(session, item, limits_provider)
                subscription.is_active = True
                subscription.region_code = region_code
                subscription.target_price = item.target_price
                subscription.target_effective_price = item.target_effective_price
                session.commit()
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


def _normalize_watchlist_product_url(
    session: Session, url: str
) -> NormalizedProductUrl:
    try:
        return normalize_product_url(url)
    except UnsupportedSourceError as original_error:
        configured = _normalize_configured_store_product_url(session, url)
        if configured is not None:
            return configured
        raise UnsupportedSourceError("unsupported_monitoring_store") from original_error


def _normalize_configured_store_product_url(
    session: Session,
    url: str,
) -> NormalizedProductUrl | None:
    parsed = urlsplit(url)
    hostname = parsed.hostname.lower().strip(".") if parsed.hostname else ""
    if parsed.scheme != "https" or not hostname:
        return None

    source = _enabled_source_for_hostname(session, hostname)
    if source is None:
        return None

    external_product_id = _generic_external_product_id(parsed.path)
    if external_product_id is None:
        raise UnsupportedSourceError("unsupported_monitoring_store")

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    canonical_query = urlencode(
        [
            (key, value)
            for key, value in query_pairs
            if _is_safe_canonical_query_key(key)
        ]
    )
    canonical_url = urlunsplit(("https", hostname, parsed.path, canonical_query, ""))
    region_code = _first_non_empty_query_value(query_pairs, "region") or "default"
    variant = _first_non_empty_query_value(query_pairs, "variant")
    variant_hash = (
        hashlib.sha256(variant.encode("utf-8")).hexdigest() if variant else None
    )
    return NormalizedProductUrl(
        source=source.source_code,
        external_product_id=external_product_id,
        canonical_url=canonical_url,
        region_code=region_code,
        variant_hash=variant_hash,
    )


def _enabled_source_for_hostname(session: Session, hostname: str) -> StoreSource | None:
    sources = session.scalars(
        select(StoreSource)
        .join(Store)
        .where(
            Store.enabled.is_(True),
            StoreSource.enabled.is_(True),
        )
        .order_by(StoreSource.priority.asc(), StoreSource.id.asc())
    ).all()
    for source in sources:
        for domain in source.domains_json or []:
            normalized_domain = domain.lower().strip(".")
            if hostname == normalized_domain or hostname.endswith(
                f".{normalized_domain}"
            ):
                return source
    return None


def _generic_external_product_id(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None
    for part in reversed(parts):
        if part.lower() not in {"product", "products", "catalog", "item", "goods"}:
            return part[:191]
    return parts[-1][:191]


def _is_safe_canonical_query_key(key: str) -> bool:
    lowered_key = key.lower()
    if lowered_key.startswith("utm_") or lowered_key in {
        "ref",
        "from",
        "gclid",
        "yclid",
    }:
        return False
    return key in {"region", "variant", "targetUrl"}


def _first_non_empty_query_value(
    query_pairs: list[tuple[str, str]],
    key: str,
) -> str | None:
    for query_key, query_value in query_pairs:
        if query_key == key and query_value:
            return query_value
    return None


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
