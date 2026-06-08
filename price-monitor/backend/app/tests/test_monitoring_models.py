from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint

from app.db import Base
from app.models.monitoring import (
    FetchJob,
    NotificationEvent,
    PriceHistory,
    SourceConfig,
    SourceHealthEvent,
    TrackedProduct,
    TrackedProductCashback,
    UserProductSubscription,
)


def _unique_constraint_columns(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_key_targets(table_name: str) -> set[tuple[str, str, str]]:
    table = Base.metadata.tables[table_name]
    targets: set[tuple[str, str, str]] = set()

    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue

        for element in constraint.elements:
            targets.add(
                (
                    element.parent.name,
                    element.column.table.name,
                    element.column.name,
                )
            )

    return targets


def test_monitoring_tables_are_registered_in_metadata() -> None:
    assert {
        "tracked_products",
        "user_product_subscriptions",
        "price_history",
        "fetch_jobs",
        "notification_events",
        "source_configs",
        "source_health_events",
    }.issubset(Base.metadata.tables)


def test_monitoring_unique_constraints_are_declared() -> None:
    assert (
        "source",
        "external_product_id",
        "region_code",
        "variant_hash",
    ) in _unique_constraint_columns("tracked_products")

    assert (
        "site_id",
        "external_user_id",
        "tracked_product_id",
    ) in _unique_constraint_columns("user_product_subscriptions")

    assert ("source_code",) in _unique_constraint_columns("source_configs")


def test_monitoring_foreign_keys_point_to_tracked_products() -> None:
    assert ("tracked_product_id", "tracked_products", "id") in _foreign_key_targets(
        "user_product_subscriptions"
    )
    assert ("tracked_product_id", "tracked_products", "id") in _foreign_key_targets(
        "price_history"
    )
    assert ("tracked_product_id", "tracked_products", "id") in _foreign_key_targets(
        "fetch_jobs"
    )
    assert ("tracked_product_id", "tracked_products", "id") in _foreign_key_targets(
        "notification_events"
    )
    assert (
        "subscription_id",
        "user_product_subscriptions",
        "id",
    ) in _foreign_key_targets("notification_events")


def test_monitoring_relationships_link_tracked_product_children() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tracked_product = TrackedProduct(
            id=1,
            source="market",
            external_product_id="sku-1",
            canonical_url="https://example.test/product/sku-1",
        )
        subscription = UserProductSubscription(
            id=1,
            site_id="site-1",
            external_user_id="user-1",
            tracked_product=tracked_product,
            target_price=Decimal("199.99"),
        )
        price_history = PriceHistory(
            id=1,
            tracked_product=tracked_product,
            price_current=Decimal("249.99"),
            currency="RUB",
            availability=True,
        )
        fetch_job = FetchJob(
            id=1,
            tracked_product=tracked_product,
            next_run_at=datetime(2026, 6, 1, tzinfo=UTC),
        )

        session.add_all([subscription, price_history, fetch_job])
        session.flush()

        assert subscription.tracked_product is tracked_product
        assert price_history.tracked_product is tracked_product
        assert fetch_job.tracked_product is tracked_product
        assert tracked_product.subscriptions == [subscription]
        assert tracked_product.price_history == [price_history]
        assert tracked_product.fetch_jobs == [fetch_job]


def test_monitoring_defaults_are_applied_on_flush() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tracked_product = TrackedProduct(
            id=1,
            source="market",
            external_product_id="sku-1",
            canonical_url="https://example.test/product/sku-1",
        )
        subscription = UserProductSubscription(
            id=1,
            site_id="site-1",
            external_user_id="user-1",
            tracked_product=tracked_product,
        )
        fetch_job = FetchJob(
            id=1,
            tracked_product=tracked_product,
            next_run_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        notification_event = NotificationEvent(
            id=1,
            site_id="site-1",
            external_user_id="user-1",
            subscription=subscription,
            tracked_product=tracked_product,
            event_type="target_price_reached",
            payload_json="{}",
        )

        session.add_all([tracked_product, subscription, fetch_job, notification_event])
        session.flush()

        assert tracked_product.region_code == "default"
        assert tracked_product.last_availability is True
        assert tracked_product.fail_count == 0
        assert subscription.is_active is True
        assert fetch_job.priority == 5
        assert fetch_job.status == "queued"
        assert fetch_job.attempt == 0
        assert notification_event.status == "pending"
        assert tracked_product.created_at is not None
        assert tracked_product.updated_at is not None
        assert subscription.created_at is not None
        assert subscription.updated_at is not None
        assert fetch_job.created_at is not None
        assert notification_event.created_at is not None

def test_notification_event_enum_values_are_validated_by_application() -> None:
    event = NotificationEvent(
        id=1,
        site_id="site-1",
        external_user_id="user-1",
        subscription_id=1,
        tracked_product_id=1,
        event_type="target_effective_price_reached",
        status="pending",
        payload_json="{}",
    )

    assert event.event_type == "target_effective_price_reached"
    assert event.status == "pending"

    for status in ("sent", "skipped", "failed"):
        assert (
            NotificationEvent(
                id=2,
                site_id="site-1",
                external_user_id="user-1",
                subscription_id=1,
                tracked_product_id=1,
                event_type="price_drop",
                status=status,
                payload_json="{}",
            ).status
            == status
        )

    with pytest.raises(ValueError, match="event_type"):
        NotificationEvent(
            id=3,
            site_id="site-1",
            external_user_id="user-1",
            subscription_id=1,
            tracked_product_id=1,
            event_type="email_now",
            payload_json="{}",
        )

    with pytest.raises(ValueError, match="status"):
        NotificationEvent(
            id=4,
            site_id="site-1",
            external_user_id="user-1",
            subscription_id=1,
            tracked_product_id=1,
            event_type="back_in_stock",
            status="queued",
            payload_json="{}",
        )


def test_tracked_product_cashback_table_is_registered_in_metadata() -> None:
    assert "tracked_product_cashback" in Base.metadata.tables


def test_tracked_product_cashback_foreign_key_points_to_tracked_products() -> None:
    assert ("tracked_product_id", "tracked_products", "id") in _foreign_key_targets(
        "tracked_product_cashback"
    )


def test_tracked_product_cashback_unique_tracked_product_id_is_declared() -> None:
    assert ("tracked_product_id",) in _unique_constraint_columns(
        "tracked_product_cashback"
    )


def test_tracked_product_cashback_enum_values_are_validated_by_application() -> None:
    cashback = TrackedProductCashback(
        id=1,
        tracked_product_id=1,
        cashback_status="partner_exact",
        commission_rate_type="percent",
        confidence="exact",
        display_policy="show_exact_rate",
    )

    assert cashback.cashback_status == "partner_exact"
    assert cashback.commission_rate_type == "percent"
    assert cashback.confidence == "exact"
    assert cashback.display_policy == "show_exact_rate"

    nullable_commission_type = TrackedProductCashback(
        id=2,
        tracked_product_id=2,
        cashback_status="no_partner",
        commission_rate_type=None,
        confidence="none",
        display_policy="cashback_unavailable",
    )
    assert nullable_commission_type.commission_rate_type is None

    with pytest.raises(ValueError, match="cashback_status"):
        TrackedProductCashback(
            id=3,
            tracked_product_id=3,
            cashback_status="unknown",
            confidence="none",
            display_policy="cashback_unavailable",
        )

    with pytest.raises(ValueError, match="commission_rate_type"):
        TrackedProductCashback(
            id=4,
            tracked_product_id=4,
            cashback_status="no_partner",
            commission_rate_type="bonus",
            confidence="none",
            display_policy="cashback_unavailable",
        )

    with pytest.raises(ValueError, match="confidence"):
        TrackedProductCashback(
            id=5,
            tracked_product_id=5,
            cashback_status="no_partner",
            confidence="certain",
            display_policy="cashback_unavailable",
        )

    with pytest.raises(ValueError, match="display_policy"):
        TrackedProductCashback(
            id=6,
            tracked_product_id=6,
            cashback_status="no_partner",
            confidence="none",
            display_policy="show_anything",
        )


def test_tracked_product_cashback_one_to_one_relationship() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tracked_product = TrackedProduct(
            id=1,
            source="market",
            external_product_id="sku-1",
            canonical_url="https://example.test/product/sku-1",
        )
        cashback = TrackedProductCashback(
            id=1,
            tracked_product=tracked_product,
            cashback_status="partner_estimated",
            merchant_id="merchant-1",
            merchant_name="Merchant",
            confidence="medium",
            display_policy="show_range_use_min_for_effective_price",
            expected_cashback_min=Decimal("10.00"),
            expected_cashback_max=Decimal("15.00"),
        )

        session.add(cashback)
        session.flush()

        assert cashback.tracked_product is tracked_product
        assert tracked_product.cashback is cashback


def test_source_config_is_created() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        config = SourceConfig(
            id=1,
            source_code="testshop",
            source_name="Test Shop",
            enabled=True,
            fetch_strategy="http",
            min_fetch_interval_minutes=60,
            max_failures_before_quarantine=3,
            browser_fallback_enabled=False,
        )

        session.add(config)
        session.flush()

        assert config.id == 1
        assert config.source_code == "testshop"
        assert config.source_name == "Test Shop"
        assert config.enabled is True
        assert config.fetch_strategy == "http"
        assert config.min_fetch_interval_minutes == 60
        assert config.max_failures_before_quarantine == 3
        assert config.browser_fallback_enabled is False
        assert config.created_at is not None
        assert config.updated_at is not None


def test_source_health_event_enum_values_are_validated_by_application() -> None:
    for event_type in (
        "success",
        "timeout",
        "http_403",
        "http_429",
        "parser_error",
        "price_not_found",
        "cashback_api_error",
    ):
        event = SourceHealthEvent(
            id=1,
            source_code="testshop",
            event_type=event_type,
        )

        assert event.event_type == event_type

    with pytest.raises(ValueError, match="event_type"):
        SourceHealthEvent(
            id=2,
            source_code="testshop",
            event_type="captcha_required",
        )
