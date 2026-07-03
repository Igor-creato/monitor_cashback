from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
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
