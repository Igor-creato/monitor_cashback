from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint

from app.db import Base
from app.models.monitoring import (
    FetchJob,
    PriceHistory,
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

        session.add_all([tracked_product, subscription, fetch_job])
        session.flush()

        assert tracked_product.region_code == "default"
        assert tracked_product.last_availability is True
        assert tracked_product.fail_count == 0
        assert subscription.is_active is True
        assert fetch_job.priority == 5
        assert fetch_job.status == "queued"
        assert fetch_job.attempt == 0
        assert tracked_product.created_at is not None
        assert tracked_product.updated_at is not None
        assert subscription.created_at is not None
        assert subscription.updated_at is not None
        assert fetch_job.created_at is not None


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
