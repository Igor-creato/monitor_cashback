from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from price_monitor.db.base import Base

if TYPE_CHECKING:
    from price_monitor.domains.watchlist.models import WatchlistItem


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("source_domain", "canonical_url_hash", name="uq_products_source_url_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    watchlist_items: Mapped[list[WatchlistItem]] = relationship(
        "WatchlistItem", back_populates="product"
    )
