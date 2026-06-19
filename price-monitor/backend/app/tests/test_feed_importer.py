from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.feeds.importer import (
    FeedImportResult,
    import_feed_content,
    import_feed_file,
)
from app.models.monitoring import (
    ProductFeedItem,
    ProductFeedSource,
    ProductOffer,
    Store,
    StoreSource,
    TrackedProduct,
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
        "feed_url": "https://feed.example/testshop.csv",
        "format": "csv",
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


def _item_count(session: Session) -> int:
    return session.scalar(select(func.count(ProductFeedItem.id))) or 0


def _offer_count(session: Session) -> int:
    return session.scalar(select(func.count(ProductOffer.id))) or 0


CSV_CONTENT = (
    "product_id,title,url,price,old_price,currency,category_id,image_url,availability\n"
    "ext-1,Demo Product,https://testshop.example/product/1,1990.00,2490.00,RUB,cat-1,"
    "https://testshop.example/img/1.jpg,in stock\n"
)

JSON_CONTENT = """
[
  {
    "product_id": "ext-2",
    "title": "Second Product",
    "url": "https://testshop.example/product/2",
    "price": "500.00",
    "currency": "RUB",
    "availability": "in stock"
  }
]
"""

YAML_CONTENT = """
- product_id: ext-3
  title: Third Product
  url: https://testshop.example/product/3
  price: "750.00"
  currency: RUB
  availability: in stock
"""

XML_CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog>
  <shop>
    <offers>
      <offer id="ext-4">
        <url>https://testshop.example/product/4</url>
        <price>320.00</price>
        <name>Fourth Product</name>
        <available>true</available>
      </offer>
    </offers>
  </shop>
</yml_catalog>
"""


def test_import_csv_creates_items(db_session: Session) -> None:
    source = _source(db_session, format="csv")

    result = import_feed_content(db_session, source, CSV_CONTENT)

    assert isinstance(result, FeedImportResult)
    assert result.imported_count == 1
    assert result.error_count == 0
    assert _item_count(db_session) == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.external_product_id == "ext-1"
    assert stored.canonical_url == "https://testshop.example/product/1"
    assert stored.price == Decimal("1990.00")
    assert stored.old_price == Decimal("2490.00")
    assert stored.currency == "RUB"
    assert stored.availability == "in stock"


def test_import_json_creates_items(db_session: Session) -> None:
    source = _source(db_session, format="json")

    result = import_feed_content(db_session, source, JSON_CONTENT)

    assert result.imported_count == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.external_product_id == "ext-2"
    assert stored.price == Decimal("500.00")


def test_import_yaml_creates_items(db_session: Session) -> None:
    source = _source(db_session, format="yml")

    result = import_feed_content(db_session, source, YAML_CONTENT)

    assert result.imported_count == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.external_product_id == "ext-3"
    assert stored.price == Decimal("750.00")


def test_import_xml_creates_items(db_session: Session) -> None:
    source = _source(db_session, format="xml")

    result = import_feed_content(db_session, source, XML_CONTENT)

    assert result.imported_count == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.external_product_id == "ext-4"
    assert stored.canonical_url == "https://testshop.example/product/4"
    assert stored.price == Decimal("320.00")


def test_invalid_price_skipped_as_item_error(db_session: Session) -> None:
    source = _source(db_session, format="csv")
    content = (
        "product_id,title,url,price,currency,availability\n"
        "ext-good,Good,https://testshop.example/good,100.00,RUB,in stock\n"
        "ext-bad,Bad,https://testshop.example/bad,not-a-number,RUB,in stock\n"
    )

    result = import_feed_content(db_session, source, content)

    # The valid row is imported, the broken one becomes an item-level error.
    assert result.imported_count == 1
    assert result.error_count == 1
    assert _item_count(db_session) == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.canonical_url == "https://testshop.example/good"
    error = result.errors[0]
    assert error.index == 1
    assert "price" in error.reason.lower()


def test_missing_url_skipped_as_item_error(db_session: Session) -> None:
    source = _source(db_session, format="csv")
    content = (
        "product_id,title,url,price,currency,availability\n"
        "ext-no-url,No URL,,100.00,RUB,in stock\n"
    )

    result = import_feed_content(db_session, source, content)

    assert result.imported_count == 0
    assert result.error_count == 1
    assert _item_count(db_session) == 0


def test_duplicate_url_updates_item(db_session: Session) -> None:
    source = _source(db_session, format="csv")
    first = (
        "product_id,title,url,price,currency,availability\n"
        "ext-1,Demo Product,https://testshop.example/product/1,1990.00,RUB,in stock\n"
    )
    second = (
        "product_id,title,url,price,currency,availability\n"
        "ext-1,Updated Product,https://testshop.example/product/1,"
        "1500.00,RUB,in stock\n"
    )

    import_feed_content(db_session, source, first)
    result = import_feed_content(db_session, source, second)

    assert result.imported_count == 1
    assert _item_count(db_session) == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.price == Decimal("1500.00")
    assert stored.title == "Updated Product"


def test_currency_and_availability_fallback(db_session: Session) -> None:
    source = _source(db_session, format="csv", currency="USD")
    content = (
        "product_id,title,url,price\n"
        "ext-1,No Currency,https://testshop.example/product/1,12.00\n"
    )

    result = import_feed_content(db_session, source, content)

    assert result.imported_count == 1
    stored = db_session.scalar(select(ProductFeedItem))
    assert stored is not None
    assert stored.currency == "USD"
    assert stored.availability == "out of stock"


def test_import_file_reads_local_path(db_session: Session, tmp_path) -> None:
    source = _source(db_session, format="csv")
    feed_path = tmp_path / "feed.csv"
    feed_path.write_text(CSV_CONTENT, encoding="utf-8")

    result = import_feed_file(db_session, source, feed_path)

    assert result.imported_count == 1
    assert _item_count(db_session) == 1


def test_import_materializes_matching_product_offer(db_session: Session) -> None:
    source = _source(db_session, format="csv")
    store = Store(store_code="testshop", display_name="Test Shop", enabled=True)
    tracked = TrackedProduct(
        source="ozon",
        external_product_id="ozon-s24-ultra",
        canonical_url="https://ozon.ru/product/s24-ultra",
        region_code="default",
        product_name="Samsung Galaxy S24 Ultra 12/512GB Black",
        last_price=Decimal("120000.00"),
        currency="RUB",
    )
    db_session.add_all([store, tracked])
    db_session.flush()
    db_session.add(
        StoreSource(
            store=store,
            source_code=source.source_code,
            display_name="Test Shop Feed",
            source_type="feed",
            enabled=True,
            metadata_json={"matching": {"min_match_score": 65}},
        )
    )
    db_session.commit()
    content = (
        "product_id,title,url,price,currency,availability\n"
        "feed-s24,Samsung Galaxy S24 Ultra 512GB Black,"
        "https://testshop.example/s24,99990.00,RUB,in stock\n"
    )

    result = import_feed_content(db_session, source, content)

    assert result.imported_count == 1
    assert _offer_count(db_session) == 1
    offer = db_session.scalar(select(ProductOffer))
    assert offer is not None
    assert offer.external_product_id == "feed-s24"
    assert offer.match_confidence == "exact"
    assert offer.match_label == "same_product"
    assert offer.raw_json["match_status"] == "exact"
    assert offer.raw_json["match_score"] >= 95
    assert offer.raw_json["match_explanation"]["ai_rerank"] == "disabled"


def test_import_respects_admin_matching_threshold(db_session: Session) -> None:
    source = _source(db_session, format="csv")
    store = Store(store_code="testshop", display_name="Test Shop", enabled=True)
    tracked = TrackedProduct(
        source="ozon",
        external_product_id="ozon-iphone-15-pro",
        canonical_url="https://ozon.ru/product/iphone-15-pro",
        region_code="default",
        product_name="Apple iPhone 15 Pro 256GB Black",
        last_price=Decimal("100000.00"),
        currency="RUB",
    )
    db_session.add_all([store, tracked])
    db_session.flush()
    db_session.add(
        StoreSource(
            store=store,
            source_code=source.source_code,
            display_name="Test Shop Feed",
            source_type="feed",
            enabled=True,
            metadata_json={"matching": {"min_match_score": 96}},
        )
    )
    db_session.commit()
    content = (
        "product_id,title,url,price,currency,availability\n"
        "feed-iphone,Apple iPhone 15 Pro Max 256GB Black,"
        "https://testshop.example/iphone,89990.00,RUB,in stock\n"
    )

    result = import_feed_content(db_session, source, content)

    assert result.imported_count == 1
    assert _offer_count(db_session) == 0
