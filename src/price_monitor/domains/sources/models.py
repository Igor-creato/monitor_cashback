from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from price_monitor.db.base import Base


class SourceStatus(Base):
    __tablename__ = "source_statuses"

    source_domain: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    reason: Mapped[str | None] = mapped_column(String(255))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
