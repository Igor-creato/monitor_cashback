from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db import Base

CASHBACK_STATUS_VALUES = frozenset(
    {
        "no_partner",
        "partner_unknown_product",
        "partner_product_found",
        "partner_no_commission",
        "partner_estimated",
        "partner_exact",
    }
)
COMMISSION_RATE_TYPE_VALUES = frozenset({"percent", "fixed"})
CONFIDENCE_VALUES = frozenset({"none", "low", "medium", "high", "exact"})
DISPLAY_POLICY_VALUES = frozenset(
    {
        "show_exact_rate",
        "show_range_use_min_for_effective_price",
        "show_possible_do_not_reduce_effective_price",
        "cashback_unavailable",
        "cashback_unknown_requires_check",
    }
)


def _validate_choice(
    field_name: str,
    value: str | None,
    allowed_values: frozenset[str],
    *,
    nullable: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if value not in allowed_values:
        raise ValueError(f"{field_name} must be one of {sorted(allowed_values)}")
    return value


class TrackedProduct(Base):
    __tablename__ = "tracked_products"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "external_product_id",
            "region_code",
            "variant_hash",
            name="uq_tracked_products_identity",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(191), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    region_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default",
        server_default="default",
    )
    variant_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    last_old_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    last_availability: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fail_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    subscriptions: Mapped[list[UserProductSubscription]] = relationship(
        back_populates="tracked_product",
        cascade="all, delete-orphan",
    )
    price_history: Mapped[list[PriceHistory]] = relationship(
        back_populates="tracked_product",
        cascade="all, delete-orphan",
    )
    fetch_jobs: Mapped[list[FetchJob]] = relationship(
        back_populates="tracked_product",
        cascade="all, delete-orphan",
    )
    cashback: Mapped[TrackedProductCashback | None] = relationship(
        back_populates="tracked_product",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TrackedProductCashback(Base):
    __tablename__ = "tracked_product_cashback"
    __table_args__ = (
        UniqueConstraint(
            "tracked_product_id",
            name="uq_tracked_product_cashback_tracked_product_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tracked_product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    cashback_status: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    network: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offer_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    rate_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    commission_rate_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    commission_exact: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    commission_min: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    commission_max: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    user_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    user_cashback_exact_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    user_cashback_min_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    user_cashback_max_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    expected_cashback_exact: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    expected_cashback_min: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    expected_cashback_max: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    effective_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    effective_price_conservative: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    display_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tracked_product: Mapped[TrackedProduct] = relationship(
        back_populates="cashback",
    )

    @validates("cashback_status")
    def validate_cashback_status(self, _: str, value: str) -> str:
        return _validate_choice("cashback_status", value, CASHBACK_STATUS_VALUES)

    @validates("commission_rate_type")
    def validate_commission_rate_type(self, _: str, value: str | None) -> str | None:
        return _validate_choice(
            "commission_rate_type",
            value,
            COMMISSION_RATE_TYPE_VALUES,
            nullable=True,
        )

    @validates("confidence")
    def validate_confidence(self, _: str, value: str) -> str:
        return _validate_choice("confidence", value, CONFIDENCE_VALUES)

    @validates("display_policy")
    def validate_display_policy(self, _: str, value: str) -> str:
        return _validate_choice("display_policy", value, DISPLAY_POLICY_VALUES)


class UserProductSubscription(Base):
    __tablename__ = "user_product_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "external_user_id",
            "tracked_product_id",
            name="uq_user_product_subscriptions_identity",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    site_id: Mapped[str] = mapped_column(String(191), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(191), nullable=False)
    tracked_product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_effective_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tracked_product: Mapped[TrackedProduct] = relationship(
        back_populates="subscriptions",
    )


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tracked_product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    price_current: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    price_old: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[bool] = mapped_column(Boolean, nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    tracked_product: Mapped[TrackedProduct] = relationship(
        back_populates="price_history",
    )


class FetchJob(Base):
    __tablename__ = "fetch_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tracked_product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="queued",
        server_default="queued",
    )
    attempt: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    tracked_product: Mapped[TrackedProduct] = relationship(
        back_populates="fetch_jobs",
    )
