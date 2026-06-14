from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.models.monitoring import (
    PriceHistory,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)

DEMO_SITE_ID = "savelloclub.ru"
DEMO_EXTERNAL_USER_ID = "wp:savelloclub.ru:demo"
DEMO_REGION_CODE = "default"
DEMO_CURRENCY = "RUB"

_WAVE_OFFSETS = (
    Decimal("0.00"),
    Decimal("820.00"),
    Decimal("1650.00"),
    Decimal("2380.00"),
    Decimal("2920.00"),
    Decimal("3180.00"),
    Decimal("3040.00"),
    Decimal("2520.00"),
    Decimal("1740.00"),
    Decimal("840.00"),
    Decimal("-120.00"),
    Decimal("-980.00"),
    Decimal("-1690.00"),
    Decimal("-2180.00"),
    Decimal("-2390.00"),
    Decimal("-2290.00"),
    Decimal("-1840.00"),
    Decimal("-1110.00"),
    Decimal("-230.00"),
    Decimal("710.00"),
    Decimal("1540.00"),
    Decimal("2190.00"),
    Decimal("2570.00"),
    Decimal("2640.00"),
    Decimal("2380.00"),
    Decimal("1840.00"),
    Decimal("1070.00"),
    Decimal("180.00"),
    Decimal("-720.00"),
    Decimal("-1480.00"),
)


@dataclass(frozen=True)
class DemoProductSeed:
    source: str
    source_display_name: str
    external_product_id: str
    canonical_url: str
    title: str
    image_url: str
    base_price: Decimal
    target_price: Decimal
    target_effective_price: Decimal | None
    cashback_status: str


@dataclass(frozen=True)
class DemoSeedResult:
    site_id: str
    external_user_id: str
    tracked_product_ids: tuple[int, ...]
    subscription_ids: tuple[int, ...]
    product_count: int
    subscription_count: int
    history_point_count: int


class DemoSeedEnvironmentError(RuntimeError):
    """Raised when demo seed is invoked outside development."""


_DEMO_PRODUCTS = (
    DemoProductSeed(
        source="ozon",
        source_display_name="Ozon",
        external_product_id="demo-gpu-ozon-rtx-5070",
        canonical_url="https://demo.invalid/ozon/demo-gpu-rtx-5070",
        title="Palit GeForce RTX 5070 GamingPro 12GB",
        image_url="https://demo.invalid/images/gpu-ozon-rtx-5070.jpg",
        base_price=Decimal("88990.00"),
        target_price=Decimal("84990.00"),
        target_effective_price=Decimal("82990.00"),
        cashback_status="partner_estimated",
    ),
    DemoProductSeed(
        source="dns",
        source_display_name="DNS",
        external_product_id="demo-gpu-dns-rx-7800-xt",
        canonical_url="https://demo.invalid/dns/demo-gpu-rx-7800-xt",
        title="Sapphire Radeon RX 7800 XT Pulse 16GB",
        image_url="https://demo.invalid/images/gpu-dns-rx-7800-xt.jpg",
        base_price=Decimal("64990.00"),
        target_price=Decimal("61990.00"),
        target_effective_price=None,
        cashback_status="no_partner",
    ),
)


def seed_demo_data(
    session: Session,
    *,
    app_env: str,
    now: datetime | None = None,
) -> DemoSeedResult:
    _ensure_development(app_env)
    seed_now = _normalize_now(now)
    tracked_product_ids: list[int] = []
    subscription_ids: list[int] = []

    for demo_product in _DEMO_PRODUCTS:
        product = _upsert_product(session, demo_product, seed_now)
        session.flush()
        tracked_product_ids.append(product.id)

        subscription = _upsert_subscription(session, product, demo_product)
        session.flush()
        subscription_ids.append(subscription.id)

        _upsert_cashback(session, product, demo_product, seed_now)

    session.execute(
        delete(PriceHistory).where(
            PriceHistory.tracked_product_id.in_(tracked_product_ids),
        ),
    )

    history_point_count = 0
    for demo_product, tracked_product_id in zip(
        _DEMO_PRODUCTS,
        tracked_product_ids,
        strict=True,
    ):
        points = _build_history_points(
            tracked_product_id=tracked_product_id,
            demo_product=demo_product,
            now=seed_now,
        )
        session.add_all(points)
        history_point_count += len(points)
        latest_point = points[-1]
        product = session.get(TrackedProduct, tracked_product_id)
        if product is not None:
            product.last_price = latest_point.price_current
            product.last_old_price = latest_point.price_old
            product.currency = latest_point.currency
            product.last_availability = latest_point.availability
            product.last_checked_at = latest_point.fetched_at
            product.last_success_at = latest_point.fetched_at
            product.last_status = "ok"

    session.flush()
    return DemoSeedResult(
        site_id=DEMO_SITE_ID,
        external_user_id=DEMO_EXTERNAL_USER_ID,
        tracked_product_ids=tuple(tracked_product_ids),
        subscription_ids=tuple(subscription_ids),
        product_count=len(tracked_product_ids),
        subscription_count=len(subscription_ids),
        history_point_count=history_point_count,
    )


def main() -> int:
    if SessionLocal is None:
        print("Database is not configured. Set DATABASE_URL before running demo seed.")
        return 1

    try:
        _ensure_development(settings.app_env)
    except DemoSeedEnvironmentError as exc:
        print(str(exc))
        return 1

    with SessionLocal() as session:
        result = seed_demo_data(session, app_env=settings.app_env)
        session.commit()

    print(
        "Seeded demo data: "
        f"{result.product_count} products, "
        f"{result.subscription_count} subscriptions, "
        f"{result.history_point_count} history points "
        f"for {result.external_user_id}."
    )
    return 0


def _ensure_development(app_env: str) -> None:
    if app_env.strip().lower() != "development":
        raise DemoSeedEnvironmentError(
            "Demo seed data can only run with APP_ENV=development.",
        )


def _normalize_now(now: datetime | None) -> datetime:
    value = now or datetime.now(UTC)
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=0)


def _upsert_product(
    session: Session,
    demo_product: DemoProductSeed,
    now: datetime,
) -> TrackedProduct:
    product = session.scalar(
        select(TrackedProduct).where(
            TrackedProduct.source == demo_product.source,
            TrackedProduct.external_product_id == demo_product.external_product_id,
            TrackedProduct.region_code == DEMO_REGION_CODE,
            TrackedProduct.variant_hash.is_(None),
        ),
    )
    if product is None:
        product = TrackedProduct(
            source=demo_product.source,
            external_product_id=demo_product.external_product_id,
            canonical_url=demo_product.canonical_url,
            region_code=DEMO_REGION_CODE,
        )
        session.add(product)

    product.canonical_url = demo_product.canonical_url
    product.product_name = demo_product.title
    product.image_url = demo_product.image_url
    product.image_object_key = None
    product.source_display_name = demo_product.source_display_name
    product.currency = DEMO_CURRENCY
    product.last_availability = True
    product.last_checked_at = now
    product.last_success_at = now
    product.last_status = "ok"
    product.fail_count = 0
    return product


def _upsert_subscription(
    session: Session,
    product: TrackedProduct,
    demo_product: DemoProductSeed,
) -> UserProductSubscription:
    subscription = session.scalar(
        select(UserProductSubscription).where(
            UserProductSubscription.site_id == DEMO_SITE_ID,
            UserProductSubscription.external_user_id == DEMO_EXTERNAL_USER_ID,
            UserProductSubscription.tracked_product_id == product.id,
        ),
    )
    if subscription is None:
        subscription = UserProductSubscription(
            site_id=DEMO_SITE_ID,
            external_user_id=DEMO_EXTERNAL_USER_ID,
            tracked_product_id=product.id,
        )
        session.add(subscription)

    subscription.target_price = demo_product.target_price
    subscription.target_effective_price = demo_product.target_effective_price
    subscription.is_active = True
    return subscription


def _upsert_cashback(
    session: Session,
    product: TrackedProduct,
    demo_product: DemoProductSeed,
    now: datetime,
) -> TrackedProductCashback:
    cashback = session.scalar(
        select(TrackedProductCashback).where(
            TrackedProductCashback.tracked_product_id == product.id,
        ),
    )
    if cashback is None:
        cashback = TrackedProductCashback(tracked_product_id=product.id)
        session.add(cashback)

    cashback.cashback_status = demo_product.cashback_status
    cashback.checked_at = now
    if demo_product.cashback_status == "partner_estimated":
        cashback.merchant_id = "demo-ozon"
        cashback.merchant_name = "Ozon"
        cashback.network = "demo"
        cashback.offer_id = "demo-ozon-gpu"
        cashback.rate_id = "demo-rate-ozon-gpu"
        cashback.commission_rate_type = "percent"
        cashback.commission_exact = None
        cashback.commission_min = Decimal("2.0000")
        cashback.commission_max = Decimal("4.0000")
        cashback.user_share = Decimal("0.7000")
        cashback.user_cashback_exact_rate = None
        cashback.user_cashback_min_rate = Decimal("1.4000")
        cashback.user_cashback_max_rate = Decimal("2.8000")
        cashback.expected_cashback_exact = None
        cashback.expected_cashback_min = Decimal("1200.00")
        cashback.expected_cashback_max = Decimal("2400.00")
        cashback.effective_price = None
        cashback.effective_price_conservative = demo_product.base_price - Decimal(
            "1200.00",
        )
        cashback.confidence = "medium"
        cashback.display_policy = "show_range_use_min_for_effective_price"
        cashback.message = "Демо-оценка кэшбэка для локальной проверки карточки."
    else:
        cashback.merchant_id = None
        cashback.merchant_name = None
        cashback.network = None
        cashback.offer_id = None
        cashback.rate_id = None
        cashback.commission_rate_type = None
        cashback.commission_exact = None
        cashback.commission_min = None
        cashback.commission_max = None
        cashback.user_share = None
        cashback.user_cashback_exact_rate = None
        cashback.user_cashback_min_rate = None
        cashback.user_cashback_max_rate = None
        cashback.expected_cashback_exact = None
        cashback.expected_cashback_min = None
        cashback.expected_cashback_max = None
        cashback.effective_price = None
        cashback.effective_price_conservative = None
        cashback.confidence = "none"
        cashback.display_policy = "cashback_unavailable"
        cashback.message = "Для этого демо-товара партнёрский кэшбэк недоступен."

    cashback.raw_response_json = None
    return cashback


def _build_history_points(
    *,
    tracked_product_id: int,
    demo_product: DemoProductSeed,
    now: datetime,
) -> list[PriceHistory]:
    points: list[PriceHistory] = []
    for index, offset in enumerate(_WAVE_OFFSETS):
        price = demo_product.base_price + offset
        fetched_at = now - timedelta(days=29 - index)
        points.append(
            PriceHistory(
                tracked_product_id=tracked_product_id,
                price_current=price,
                price_old=price + Decimal("3500.00"),
                currency=DEMO_CURRENCY,
                availability=True,
                seller_name=demo_product.source_display_name,
                fetched_at=fetched_at,
            ),
        )
    return points


if __name__ == "__main__":
    raise SystemExit(main())
