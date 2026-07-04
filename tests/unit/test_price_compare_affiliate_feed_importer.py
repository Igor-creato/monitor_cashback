from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from price_monitor.db.base import Base
from price_monitor.price_compare.feed_importer import AffiliateFeedImportService
from price_monitor.price_compare.models import AffiliateFeedSource, FeedImportRun, Offer


def test_affiliate_feed_importer_discovers_downloads_and_upserts_feed_offers() -> None:
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    bridge = FakeBridge(
        [
            {
                "network": "admitad",
                "store_domain": "merchant.test",
                "store_name": "Merchant",
                "offer_id": "campaign-10",
                "feed_id": "feed-csv",
                "format": "csv",
                "feed_url_secret": True,
            }
        ],
        b"id;title;url;price;currency\nsku-1;Redmi Note 13;https://merchant.test/p/1;12990;RUB\n",
    )

    with Session(engine) as session:
        result = AffiliateFeedImportService(session, bridge=bridge).import_configured_feeds()

        offers = list(session.scalars(select(Offer)))
        feed_sources = list(session.scalars(select(AffiliateFeedSource)))
        runs = list(session.scalars(select(FeedImportRun)))

    assert result.status == "success"
    assert result.created_count == 1
    assert result.updated_count == 0
    assert result.skipped_count == 0
    assert bridge.downloaded_feed_ids == ["feed-csv"]
    assert len(offers) == 1
    assert offers[0].source == "admitad_product_feed"
    assert offers[0].store_domain == "merchant.test"
    assert offers[0].price == 12990
    assert len(feed_sources) == 1
    assert feed_sources[0].feed_url_secret is True
    assert len(runs) == 1
    assert runs[0].status == "success"
    assert runs[0].created_count == 1


def test_affiliate_feed_importer_is_idempotent_for_existing_offer() -> None:
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    descriptor = {
        "network": "advcake",
        "store_domain": "merchant.test",
        "feed_id": "feed-yml",
        "format": "xml",
        "feed_url_secret": True,
    }
    first_feed = b"""<yml_catalog><shop><offers>
      <offer id="offer-1" available="true">
        <url>https://merchant.test/p/1</url><name>Redmi Note 13</name>
        <price>15990</price><currencyId>RUB</currencyId>
      </offer>
    </offers></shop></yml_catalog>"""
    second_feed = first_feed.replace(b"15990", b"14990")
    bridge = FakeBridge([descriptor], first_feed)

    with Session(engine) as session:
        service = AffiliateFeedImportService(session, bridge=bridge)
        first = service.import_configured_feeds()
        bridge.content = second_feed
        second = service.import_configured_feeds()

        offers = list(session.scalars(select(Offer)))

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.updated_count == 1
    assert len(offers) == 1
    assert offers[0].price == 14990
    assert offers[0].availability == "unknown"


def test_affiliate_feed_importer_skips_secret_url_descriptor_without_bridge_download() -> None:
    engine = _sqlite_engine()
    Base.metadata.create_all(engine)
    bridge = FakeBridge(
        [
            {
                "network": "admitad",
                "store_domain": "merchant.test",
                "feed_id": "feed-csv",
                "format": "csv",
                "feed_url_secret": True,
            }
        ],
        None,
    )

    with Session(engine) as session:
        result = AffiliateFeedImportService(session, bridge=bridge).import_configured_feeds()
        offers = list(session.scalars(select(Offer)))
        runs = list(session.scalars(select(FeedImportRun)))

    assert result.status == "partial"
    assert result.skipped_count == 1
    assert offers == []
    assert runs[0].status == "failed"
    assert "secret" not in (runs[0].error_message or "").lower()


class FakeBridge:
    def __init__(self, descriptors: list[dict[str, object]], content: bytes | None) -> None:
        self.descriptors = descriptors
        self.content = content
        self.downloaded_feed_ids: list[str] = []

    def feed_descriptors(self) -> dict[str, object]:
        return {"items": self.descriptors}

    def download_feed(self, descriptor: dict[str, object]) -> bytes:
        self.downloaded_feed_ids.append(str(descriptor["feed_id"]))
        if self.content is None:
            raise RuntimeError("download unavailable")
        return self.content


def _sqlite_engine():
    return create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
