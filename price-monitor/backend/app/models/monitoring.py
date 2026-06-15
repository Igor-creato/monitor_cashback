from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
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
NOTIFICATION_EVENT_TYPE_VALUES = frozenset(
    {
        "target_price_reached",
        "target_effective_price_reached",
        "price_drop",
        "back_in_stock",
    }
)
NOTIFICATION_STATUS_VALUES = frozenset({"pending", "sent", "skipped", "failed"})
SOURCE_HEALTH_EVENT_TYPE_VALUES = frozenset(
    {
        "success",
        "timeout",
        "http_403",
        "http_429",
        "parser_error",
        "captcha_detected",
        "price_not_found",
        "cashback_api_error",
    }
)
FETCH_ATTEMPT_STATUS_VALUES = frozenset({"success", "failed", "skipped", "quarantined"})
SOURCE_QUARANTINE_STATUS_VALUES = frozenset(
    {"active", "cooldown", "quarantined", "disabled"}
)
MARKETPLACE_CONNECTION_STATUS_VALUES = frozenset(
    {
        "connecting",
        "connected",
        "sync_failed_retryable",
        "source_limited",
        "reconnect_required",
        "disconnected",
    }
)
MARKETPLACE_SESSION_VALUE_KIND_VALUES = frozenset({"cookie", "token"})
MARKETPLACE_SESSION_AUDIT_EVENT_TYPE_VALUES = frozenset(
    {
        "connect",
        "decrypt_for_sync",
        "sync_auth_failure",
        "rotation",
        "disconnect",
        "delete",
        "reconnect_required",
        "kill_switch_blocked",
    }
)
MARKETPLACE_SESSION_AUDIT_ACTOR_TYPE_VALUES = frozenset(
    {"user", "worker", "admin", "system"}
)
SOURCE_DIFFICULTY_CLASS_VALUES = frozenset({"light", "medium", "heavy"})
SOURCE_TRANSPORT_VALUES = frozenset(
    {"direct_http", "curl_cffi", "crawl4ai", "playwright", "camoufox"}
)
SOURCE_PROXY_TIER_POLICY_VALUES = frozenset(
    {"none", "cheap_first", "residential_first", "premium_only"}
)
SOURCE_EXTRACTION_MODE_VALUES = frozenset({"json", "css", "hybrid"})
SOURCE_IMAGE_POLICY_VALUES = frozenset(
    {"copy_to_object_storage", "external_url_allowed"}
)
PROXY_LEASE_STATUS_VALUES = frozenset({"active", "reported", "expired"})
PROXY_HEALTH_EVENT_TYPE_VALUES = frozenset(
    {"success", "http_403", "http_429", "captcha", "timeout", "error"}
)
PROXY_HEALTH_STATUS_VALUES = frozenset({"success", "failed"})
PROXY_POOL_TIER_VALUES = frozenset(
    {"free", "cheap", "standard", "residential", "premium", "reserved"}
)
# Порядок тиров от дешёвых к дорогим; индекс используется как ceiling-компаратор.
PROXY_POOL_TIER_ORDER: list[str] = [
    "free",
    "cheap",
    "standard",
    "residential",
    "premium",
    "reserved",
]


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


def _bigint_primary_key():
    return BigInteger().with_variant(Integer, "sqlite")


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

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
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
    image_object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
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
    notification_events: Mapped[list[NotificationEvent]] = relationship(
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

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
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


class SourceConfig(Base):
    __tablename__ = "source_configs"
    __table_args__ = (
        UniqueConstraint("source_code", name="uq_source_configs_source_code"),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fetch_strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    min_fetch_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    max_failures_before_quarantine: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    browser_fallback_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
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


class SourceFetchProfile(Base):
    __tablename__ = "source_fetch_profiles"
    __table_args__ = (
        UniqueConstraint("source_code", name="uq_source_fetch_profiles_source_code"),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    difficulty_class: Mapped[str] = mapped_column(String(16), nullable=False)
    preferred_transport: Mapped[str] = mapped_column(String(32), nullable=False)
    fallback_transports: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    proxy_tier_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    browser_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    extraction_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    image_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
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

    @validates("difficulty_class")
    def validate_difficulty_class(self, _: str, value: str) -> str:
        return _validate_choice(
            "difficulty_class",
            value,
            SOURCE_DIFFICULTY_CLASS_VALUES,
        )

    @validates("preferred_transport")
    def validate_preferred_transport(self, _: str, value: str) -> str:
        return _validate_choice(
            "preferred_transport",
            value,
            SOURCE_TRANSPORT_VALUES,
        )

    @validates("fallback_transports")
    def validate_fallback_transports(self, _: str, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("fallback_transports must be a list")
        for transport in value:
            _validate_choice(
                "fallback_transports",
                transport,
                SOURCE_TRANSPORT_VALUES,
            )
        return value

    @validates("proxy_tier_policy")
    def validate_proxy_tier_policy(self, _: str, value: str) -> str:
        return _validate_choice(
            "proxy_tier_policy",
            value,
            SOURCE_PROXY_TIER_POLICY_VALUES,
        )

    @validates("extraction_mode")
    def validate_extraction_mode(self, _: str, value: str) -> str:
        return _validate_choice(
            "extraction_mode",
            value,
            SOURCE_EXTRACTION_MODE_VALUES,
        )

    @validates("image_policy")
    def validate_image_policy(self, _: str, value: str) -> str:
        return _validate_choice("image_policy", value, SOURCE_IMAGE_POLICY_VALUES)


class SourceHealthEvent(Base):
    __tablename__ = "source_health_events"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    @validates("event_type")
    def validate_event_type(self, _: str, value: str) -> str:
        return _validate_choice(
            "event_type",
            value,
            SOURCE_HEALTH_EVENT_TYPE_VALUES,
        )


class MetricCounter(Base):
    __tablename__ = "metrics_counters"
    __table_args__ = (UniqueConstraint("name", name="uq_metrics_counters_name"),)

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    value: Mapped[int] = mapped_column(
        BigInteger,
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


class SourceQuarantineState(Base):
    __tablename__ = "source_quarantine_states"
    __table_args__ = (
        UniqueConstraint("source_code", name="uq_source_quarantine_states_source_code"),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quarantined_until: Mapped[datetime | None] = mapped_column(
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

    @validates("status")
    def validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, SOURCE_QUARANTINE_STATUS_VALUES)


class MarketplaceSessionSource(Base):
    __tablename__ = "marketplace_session_sources"
    __table_args__ = (
        UniqueConstraint(
            "marketplace",
            name="uq_marketplace_session_sources_marketplace",
        ),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    disabled_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(
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


class MarketplaceSessionAllowlist(Base):
    __tablename__ = "marketplace_session_allowlist"
    __table_args__ = (
        UniqueConstraint(
            "marketplace",
            "name",
            "kind",
            "scope",
            name="uq_marketplace_session_allowlist_identity",
        ),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(191), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
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

    @validates("kind")
    def validate_kind(self, _: str, value: str) -> str:
        return _validate_choice("kind", value, MARKETPLACE_SESSION_VALUE_KIND_VALUES)


class MarketplaceConnection(Base):
    __tablename__ = "marketplace_connections"
    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "external_user_id",
            "marketplace",
            name="uq_marketplace_connections_identity",
        ),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(191), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(191), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="connecting",
        server_default="connecting",
    )
    scope_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(191), nullable=False)
    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reconnect_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kill_switch_blocked_at: Mapped[datetime | None] = mapped_column(
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

    secrets: Mapped[list[MarketplaceSessionSecret]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
    )
    audit_events: Mapped[list[MarketplaceSessionAuditEvent]] = relationship(
        back_populates="connection",
        cascade="all, delete-orphan",
    )

    @validates("status")
    def validate_status(self, _: str, value: str) -> str:
        return _validate_choice(
            "status",
            value,
            MARKETPLACE_CONNECTION_STATUS_VALUES,
        )


class MarketplaceSessionSecret(Base):
    __tablename__ = "marketplace_session_secrets"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("marketplace_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    encrypted_cookie_bundle: Mapped[str] = mapped_column(Text, nullable=False)
    dek_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    tag: Mapped[str] = mapped_column(String(64), nullable=False)
    aad_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_alg: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="AES-256-GCM",
        server_default="AES-256-GCM",
    )
    bundle_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    connection: Mapped[MarketplaceConnection] = relationship(back_populates="secrets")


class MarketplaceSessionAuditEvent(Base):
    __tablename__ = "marketplace_session_audit_events"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    connection_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("marketplace_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    site_id: Mapped[str] = mapped_column(String(191), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(191), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    connection: Mapped[MarketplaceConnection | None] = relationship(
        back_populates="audit_events",
    )

    @validates("event_type")
    def validate_event_type(self, _: str, value: str) -> str:
        return _validate_choice(
            "event_type",
            value,
            MARKETPLACE_SESSION_AUDIT_EVENT_TYPE_VALUES,
        )

    @validates("actor_type")
    def validate_actor_type(self, _: str, value: str) -> str:
        return _validate_choice(
            "actor_type",
            value,
            MARKETPLACE_SESSION_AUDIT_ACTOR_TYPE_VALUES,
        )


class ProxyPool(Base):
    __tablename__ = "proxy_pools"
    __table_args__ = (
        UniqueConstraint("source", "purpose", name="uq_proxy_pools_source_purpose"),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    tier: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="standard",
        server_default="standard",
    )
    cost_per_request: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )
    cost_per_gb: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    region_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sticky_session_supported: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    max_cost_per_success: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8),
        nullable=True,
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=100,
        server_default="100",
    )
    source_affinity: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
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

    endpoints: Mapped[list[ProxyEndpoint]] = relationship(
        back_populates="pool",
        cascade="all, delete-orphan",
    )

    @validates("tier")
    def validate_tier(self, _: str, value: str) -> str:
        return _validate_choice("tier", value, PROXY_POOL_TIER_VALUES)


class ProxyEndpoint(Base):
    __tablename__ = "proxy_endpoints"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    pool_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("proxy_pools.id", ondelete="CASCADE"),
        nullable=False,
    )
    endpoint_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    current_concurrency: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    success_rate_1h: Mapped[float | None] = mapped_column(Float, nullable=True)
    success_rate_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ban_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_403_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_429_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_captcha_at: Mapped[datetime | None] = mapped_column(
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

    pool: Mapped[ProxyPool] = relationship(back_populates="endpoints")
    leases: Mapped[list[ProxyLease]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )
    health_events: Mapped[list[ProxyHealthEvent]] = relationship(
        back_populates="endpoint",
        cascade="all, delete-orphan",
    )


class ProxyLease(Base):
    __tablename__ = "proxy_leases"
    __table_args__ = (
        UniqueConstraint("lease_token", name="uq_proxy_leases_lease_token"),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("proxy_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    job_id: Mapped[str] = mapped_column(String(191), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
    )
    leased_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    endpoint: Mapped[ProxyEndpoint] = relationship(back_populates="leases")
    health_events: Mapped[list[ProxyHealthEvent]] = relationship(
        back_populates="lease",
        cascade="all, delete-orphan",
    )

    @validates("status")
    def validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, PROXY_LEASE_STATUS_VALUES)


class ProxyHealthEvent(Base):
    __tablename__ = "proxy_health_events"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    endpoint_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("proxy_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    lease_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("proxy_leases.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    endpoint: Mapped[ProxyEndpoint] = relationship(back_populates="health_events")
    lease: Mapped[ProxyLease | None] = relationship(back_populates="health_events")

    @validates("event_type")
    def validate_event_type(self, _: str, value: str) -> str:
        return _validate_choice("event_type", value, PROXY_HEALTH_EVENT_TYPE_VALUES)

    @validates("status")
    def validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, PROXY_HEALTH_STATUS_VALUES)


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

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
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

    notification_events: Mapped[list[NotificationEvent]] = relationship(
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


class NotificationEvent(Base):
    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    site_id: Mapped[str] = mapped_column(String(191), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(191), nullable=False)
    subscription_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_product_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    tracked_product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    subscription: Mapped[UserProductSubscription] = relationship(
        back_populates="notification_events",
    )
    tracked_product: Mapped[TrackedProduct] = relationship(
        back_populates="notification_events",
    )

    @validates("event_type")
    def validate_event_type(self, _: str, value: str) -> str:
        return _validate_choice(
            "event_type",
            value,
            NOTIFICATION_EVENT_TYPE_VALUES,
        )

    @validates("status")
    def validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, NOTIFICATION_STATUS_VALUES)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
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

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
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


class FetchAttempt(Base):
    __tablename__ = "fetch_attempts"

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    fetch_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("fetch_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    tracked_product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tracked_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    proxy_pool_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("proxy_pools.id", ondelete="SET NULL"),
        nullable=True,
    )
    proxy_endpoint_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("proxy_endpoints.id", ondelete="SET NULL"),
        nullable=True,
    )
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimated: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6),
        nullable=True,
    )
    bytes_downloaded: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    product_data_found: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    price_found: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    image_found: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    @validates("status")
    def validate_status(self, _: str, value: str) -> str:
        return _validate_choice("status", value, FETCH_ATTEMPT_STATUS_VALUES)


class ProductFeedSource(Base):
    __tablename__ = "product_feed_sources"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "source_code",
            "region_code",
            name="uq_product_feed_sources_identity",
        ),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String(191), nullable=False)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False)
    feed_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    region_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default",
        server_default="default",
    )
    fields_mapping_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
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

    items: Mapped[list[ProductFeedItem]] = relationship(
        back_populates="feed_source",
        cascade="all, delete-orphan",
    )


class ProductFeedItem(Base):
    __tablename__ = "product_feed_items"
    __table_args__ = (
        UniqueConstraint(
            "feed_source_id",
            "canonical_url",
            name="uq_product_feed_items_identity",
        ),
    )

    id: Mapped[int] = mapped_column(_bigint_primary_key(), primary_key=True)
    feed_source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("product_feed_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_product_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    availability: Mapped[str] = mapped_column(String(32), nullable=False)
    category_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    feed_source: Mapped[ProductFeedSource] = relationship(back_populates="items")
