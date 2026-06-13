from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.fetchers.base import PriceFetchResult
from app.models.monitoring import ProductFeedItem, ProductFeedSource, TrackedProduct
from app.services.fetch_strategy import select_fetch_strategy
from app.services.product_feeds import (
    build_price_result_from_feed_item,
    feed_item_is_fresh,
    find_feed_item_for_product,
    upsert_feed_items,
)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.product_feeds as product_feeds

    monkeypatch.setattr(product_feeds, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _source(session: Session, **overrides: object) -> ProductFeedSource:
    values: dict[str, object] = {
        "merchant_id": "merchant-1",
        "source_code": "testshop",
        "feed_url": "https://feed.example/testshop.xml",
        "format": "xml",
        "currency": "RUB",
        "region_code": "default",
        "enabled": True,
    }
    values.update(overrides)
    source = ProductFeedSource(**values)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def _item(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "external_product_id": "ext-1",
        "canonical_url": "https://testshop.example/product/1",
        "title": "Demo Product",
        "image_url": "https://testshop.example/img/1.jpg",
        "price": Decimal("1990.00"),
        "old_price": Decimal("2490.00"),
        "currency": "RUB",
        "availability": "in stock",
        "category_id": "cat-1",
        "raw_json": {"id": "ext-1"},
    }
    values.update(overrides)
    return values


def _product(**overrides: object) -> TrackedProduct:
    values: dict[str, object] = {
        "source": "testshop",
        "external_product_id": "ext-1",
        "canonical_url": "https://testshop.example/product/1",
        "region_code": "default",
    }
    values.update(overrides)
    return TrackedProduct(**values)


def _item_count(session: Session) -> int:
    return session.scalar(select(func.count(ProductFeedItem.id))) or 0


def test_upsert_saves_new_feed_item(db_session: Session) -> None:
    source = _source(db_session)

    saved = upsert_feed_items(source.id, [_item()], session=db_session)

    assert len(saved) == 1
    assert _item_count(db_session) == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.feed_source_id == source.id
    assert stored.external_product_id == "ext-1"
    assert stored.canonical_url == "https://testshop.example/product/1"
    assert stored.price == Decimal("1990.00")
    assert stored.currency == "RUB"


def test_upsert_updates_existing_feed_item(db_session: Session) -> None:
    source = _source(db_session)
    upsert_feed_items(source.id, [_item(price=Decimal("1990.00"))], session=db_session)

    upsert_feed_items(
        source.id,
        [_item(price=Decimal("1500.00"), title="Updated Product")],
        session=db_session,
    )

    assert _item_count(db_session) == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.price == Decimal("1500.00")
    assert stored.title == "Updated Product"


def test_find_feed_item_by_external_product_id(db_session: Session) -> None:
    source = _source(db_session)
    upsert_feed_items(
        source.id,
        [_item(external_product_id="ext-99", canonical_url="https://other.example/x")],
        session=db_session,
    )
    product = _product(
        external_product_id="ext-99",
        canonical_url="https://testshop.example/different-url",
    )

    found = find_feed_item_for_product(product, session=db_session)

    assert found is not None
    assert found.external_product_id == "ext-99"


def test_find_feed_item_by_canonical_url(db_session: Session) -> None:
    source = _source(db_session)
    upsert_feed_items(
        source.id,
        [
            _item(
                external_product_id=None,
                canonical_url="https://testshop.example/product/777",
            )
        ],
        session=db_session,
    )
    product = _product(
        external_product_id="missing-id",
        canonical_url="https://testshop.example/product/777",
    )

    found = find_feed_item_for_product(product, session=db_session)

    assert found is not None
    assert found.canonical_url == "https://testshop.example/product/777"


def test_build_price_result_from_feed_item(db_session: Session) -> None:
    source = _source(db_session)
    upsert_feed_items(source.id, [_item()], session=db_session)
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None

    result = build_price_result_from_feed_item(stored)

    assert isinstance(result, PriceFetchResult)
    assert result.price_current == Decimal("1990.00")
    assert result.price_old == Decimal("2490.00")
    assert result.currency == "RUB"
    assert result.availability is True
    assert result.product_name == "Demo Product"
    assert result.image_url == "https://testshop.example/img/1.jpg"
    assert result.fetched_at == stored.updated_at


def test_fresh_feed_item_selects_feed_strategy(db_session: Session) -> None:
    source = _source(db_session)
    upsert_feed_items(source.id, [_item()], session=db_session)
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None

    assert feed_item_is_fresh(stored) is True

    decision = select_fetch_strategy(
        "testshop",
        session=db_session,
        has_fresh_feed_data=feed_item_is_fresh(stored),
    )

    assert decision.strategy == "feed"


def test_stale_feed_item_does_not_select_feed_strategy(db_session: Session) -> None:
    source = _source(db_session)
    upsert_feed_items(source.id, [_item()], session=db_session)
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None

    stale_now = datetime.now(UTC) + timedelta(hours=7)

    assert feed_item_is_fresh(stored, now=stale_now) is False

    decision = select_fetch_strategy(
        "testshop",
        session=db_session,
        has_fresh_feed_data=feed_item_is_fresh(stored, now=stale_now),
    )

    assert decision.strategy != "feed"
