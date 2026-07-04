from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from price_monitor.db.base import Base


class StoreSource(Base):
    __tablename__ = "price_compare_store_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="custom", nullable=False)
    source_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(2048))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    supports_region: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_behavior: Mapped[str] = mapped_column(
        String(64), default="status_only", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Offer(Base):
    __tablename__ = "price_compare_offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    store_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("price_compare_store_sources.domain", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(1024), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(2048))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    availability: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    region_supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    city: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportStatus(Base):
    __tablename__ = "price_compare_import_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    store_domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(64), default="idle", nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AffiliateFeedSource(Base):
    __tablename__ = "price_compare_affiliate_feed_sources"
    __table_args__ = (
        UniqueConstraint(
            "network",
            "store_domain",
            "offer_id",
            "feed_id",
            name="uq_price_compare_affiliate_feed_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    store_domain: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("price_compare_store_sources.domain", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    offer_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    feed_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(32), default="xml", nullable=False)
    feed_url_hash: Mapped[str | None] = mapped_column(String(64))
    feed_url_secret: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    descriptor_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_feed_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FeedImportRun(Base):
    __tablename__ = "price_compare_feed_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("price_compare_affiliate_feed_sources.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(64), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feed_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quarantined_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)


class PriceSnapshot(Base):
    __tablename__ = "price_compare_price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("price_compare_offers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    availability: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
