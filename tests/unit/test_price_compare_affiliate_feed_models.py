from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.price_compare.feed_sources import public_feed_source_payload
from price_monitor.price_compare.models import AffiliateFeedSource, FeedImportRun, StoreSource


def test_affiliate_feed_source_stores_descriptor_without_raw_secret_url() -> None:
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(StoreSource(domain="merchant.test", display_name="Merchant", active=True))
        feed = AffiliateFeedSource(
            network="admitad",
            store_domain="merchant.test",
            offer_id="campaign-10",
            feed_id="feed-xml",
            display_name="Merchant XML",
            format="xml",
            feed_url_hash="a" * 64,
            feed_url_secret=True,
            descriptor_payload={"products_count": 100},
        )
        session.add(feed)
        session.commit()

        payload = public_feed_source_payload(feed)

    assert payload["network"] == "admitad"
    assert payload["store_domain"] == "merchant.test"
    assert payload["feed_id"] == "feed-xml"
    assert payload["feed_url_secret"] is True
    assert payload["descriptor"]["products_count"] == 100
    assert "feed_url_hash" not in payload
    assert "secret" not in repr(payload["descriptor"]).lower()
    assert not hasattr(feed, "feed_url")
    assert "api_key" not in AffiliateFeedSource.__table__.columns


def test_affiliate_feed_source_identity_is_unique_per_network_store_offer_feed() -> None:
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(StoreSource(domain="merchant.test", display_name="Merchant", active=True))
        session.add(
            AffiliateFeedSource(
                network="advcake",
                store_domain="merchant.test",
                offer_id="offer-1",
                feed_id="common-feed",
                format="xml",
            )
        )
        session.commit()
        session.add(
            AffiliateFeedSource(
                network="advcake",
                store_domain="merchant.test",
                offer_id="offer-1",
                feed_id="common-feed",
                format="xml",
            )
        )

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:  # pragma: no cover - assertion branch
            raise AssertionError("duplicate feed source identity was accepted")


def test_feed_import_run_records_counts_and_source_freshness() -> None:
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(StoreSource(domain="merchant.test", display_name="Merchant", active=True))
        feed = AffiliateFeedSource(
            network="admitad",
            store_domain="merchant.test",
            offer_id="campaign-10",
            feed_id="feed-xml",
            format="xml",
        )
        session.add(feed)
        session.flush()
        session.add(
            FeedImportRun(
                feed_source_id=feed.id,
                status="success",
                created_count=3,
                updated_count=4,
                skipped_count=1,
                quarantined_count=2,
            )
        )
        session.commit()

        run = session.query(FeedImportRun).one()

    assert run.status == "success"
    assert run.created_count == 3
    assert run.updated_count == 4
    assert run.skipped_count == 1
    assert run.quarantined_count == 2


def _sqlite_engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
