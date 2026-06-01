from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import ForeignKeyConstraint, UniqueConstraint

from app.db import Base
from app.models.monitoring import (
    FetchJob,
    PriceHistory,
    TrackedProduct,
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
