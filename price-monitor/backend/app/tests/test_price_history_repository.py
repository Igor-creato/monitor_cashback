from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import PriceHistory
from app.repositories.price_history_repository import (
    MariaDBPriceHistoryRepository,
    PriceHistoryRepository,
)


def _session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _history_point(
    session: Session,
    *,
    tracked_product_id: int = 1,
    price_current: str = "100.00",
    price_old: str | None = None,
    currency: str = "RUB",
    availability: bool = True,
    seller_name: str | None = None,
    fetched_at: datetime = datetime(2026, 6, 8, 10, 0, 0),
) -> PriceHistory:
    point = PriceHistory(
        tracked_product_id=tracked_product_id,
        price_current=Decimal(price_current),
        price_old=Decimal(price_old) if price_old is not None else None,
        currency=currency,
        availability=availability,
        seller_name=seller_name,
        fetched_at=fetched_at,
    )
    session.add(point)
    session.commit()
    return point


def test_mariadb_repository_implements_price_history_interface() -> None:
    with _session() as session:
        repository = MariaDBPriceHistoryRepository(session)

        assert isinstance(repository, PriceHistoryRepository)


def test_write_price_point_persists_same_mariadb_fields() -> None:
    fetched_at = datetime(2026, 6, 8, 10, 0, 0)
    with _session() as session:
        repository = MariaDBPriceHistoryRepository(session)

        point = repository.write_price_point(
            tracked_product_id=1,
            region_code="msk",
            price_current=Decimal("1499.90"),
            price_old=Decimal("1999.00"),
            currency="RUB",
            availability=False,
            seller_name="Test Seller",
            fetched_at=fetched_at,
        )
        session.commit()

        stored = session.scalar(select(PriceHistory))
        assert stored is not None
        assert point.id == stored.id
        assert stored.tracked_product_id == 1
        assert point.region_code == "msk"
        assert stored.region_code == "msk"
        assert stored.price_current == Decimal("1499.90")
        assert stored.price_old == Decimal("1999.00")
        assert stored.currency == "RUB"
        assert stored.availability is False
        assert stored.seller_name == "Test Seller"
        assert stored.fetched_at == fetched_at


def test_get_price_points_matches_current_query_filters_and_ordering() -> None:
    now = datetime(2026, 6, 8, 12, 0, 0)
    with _session() as session:
        repository = MariaDBPriceHistoryRepository(session)
        _history_point(
            session,
            tracked_product_id=1,
            price_current="700.00",
            fetched_at=now - timedelta(days=40),
        )
        _history_point(
            session,
            tracked_product_id=1,
            price_current="900.00",
            currency="EUR",
            fetched_at=now - timedelta(days=2),
        )
        first = _history_point(
            session,
            tracked_product_id=1,
            price_current="800.00",
            currency="USD",
            fetched_at=now - timedelta(days=2),
        )
        second = _history_point(
            session,
            tracked_product_id=1,
            price_current="850.00",
            currency="USD",
            fetched_at=now - timedelta(days=1),
        )
        _history_point(
            session,
            tracked_product_id=2,
            price_current="1000.00",
            currency="USD",
            fetched_at=now - timedelta(days=1),
        )

        points = repository.get_price_points(
            tracked_product_id=1,
            fetched_at_from=now - timedelta(days=30),
            currency="USD",
        )

        assert [point.id for point in points] == [first.id, second.id]
        assert [point.price_current for point in points] == [
            Decimal("800.00"),
            Decimal("850.00"),
        ]


def test_get_chart_summary_matches_current_raw_summary_calculation() -> None:
    now = datetime(2026, 6, 8, 12, 0, 0)
    with _session() as session:
        repository = MariaDBPriceHistoryRepository(session)
        for price, fetched_at in [
            ("743.20", now - timedelta(days=3)),
            ("793.20", now - timedelta(days=2)),
            ("843.20", now - timedelta(days=1)),
        ]:
            _history_point(
                session,
                tracked_product_id=1,
                price_current=price,
                fetched_at=fetched_at,
            )

        summary = repository.get_chart_summary(
            tracked_product_id=1,
            fetched_at_from=now - timedelta(days=30),
        )

        assert summary.current_price == Decimal("843.20")
        assert summary.avg_price == Decimal("793.20")
        assert summary.min_price == Decimal("743.20")
        assert summary.max_price == Decimal("843.20")
        assert summary.delta_vs_avg_percent == Decimal("6.30")
        assert summary.trend == "above_usual"
