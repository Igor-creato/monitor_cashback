from __future__ import annotations

import base64
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core import config
from app.db import Base
from app.models.monitoring import (
    ImportedCollection,
    ImportedItem,
    MarketplaceConnection,
    MarketplaceSessionAllowlist,
    MarketplaceSessionSource,
    MarketplaceSyncSession,
    SourceQuarantineState,
    TrackedProduct,
    UserProductSubscription,
)
from app.schemas.marketplace_sessions import (
    MarketplaceConnectionCreate,
    MarketplaceSessionBundle,
    MarketplaceSessionCookie,
    MarketplaceSessionToken,
)
from app.services.marketplace_sessions import connect_marketplace_session
from app.services.marketplace_sync_adapters import (
    MarketplaceSyncAdapterResult,
    SanitizedMarketplaceItem,
)
from app.services.marketplace_sync_worker import sync_due_marketplace_connections

SITE_ID = "savelloclub.ru"
USER_ID = "wp:savelloclub.ru:123"
NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


class FakeAdapter:
    def __init__(self, result: MarketplaceSyncAdapterResult) -> None:
        self.result = result
        self.calls: list[tuple[str, dict]] = []

    def fetch_collection(
        self,
        *,
        bundle: dict,
        collection_type: str,
    ) -> MarketplaceSyncAdapterResult:
        self.calls.append((collection_type, bundle))
        return self.result


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        config.settings,
        "marketplace_session_keyring",
        SecretStr("v1:" + base64.b64encode(b"k" * 32).decode()),
    )
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    monkeypatch.setattr(config.settings, "marketplace_sync_interval_seconds", 3600)
    monkeypatch.setattr(config.settings, "marketplace_sync_rate_limit_seconds", 900)
    monkeypatch.setattr(config.settings, "marketplace_sync_due_limit", 100)

    with Session(engine) as session:
        yield session


def _enable_marketplace(session: Session, *, enabled: bool = True) -> None:
    existing = session.scalar(
        select(MarketplaceSessionSource).where(
            MarketplaceSessionSource.marketplace == "ozon"
        )
    )
    if existing is not None:
        existing.enabled = enabled
        session.commit()
        return
    session.add(MarketplaceSessionSource(marketplace="ozon", enabled=enabled))
    session.add_all(
        [
            MarketplaceSessionAllowlist(
                marketplace="ozon",
                name="session-id",
                kind="cookie",
                scope="cart_read",
                purpose="cart_sync",
                enabled=True,
            ),
            MarketplaceSessionAllowlist(
                marketplace="ozon",
                name="x-token",
                kind="token",
                scope="favorites_read",
                purpose="favorites_sync",
                enabled=True,
            ),
        ]
    )
    session.commit()


def _connect_marketplace(
    session: Session,
    *,
    enabled: bool = True,
    scope: list[str] | None = None,
    region_hint: str = "msk",
) -> MarketplaceConnection:
    _enable_marketplace(session, enabled=enabled)
    scope = scope or ["cart_read", "favorites_read"]
    connection = connect_marketplace_session(
        session,
        MarketplaceConnectionCreate(
            site_id=SITE_ID,
            external_user_id=USER_ID,
            marketplace="ozon",
            consent_version="price-assistant-session-v1",
            scope=scope,
            captured_at=NOW,
            connector_version="0.1.0",
            session_bundle=MarketplaceSessionBundle(
                cookies=[
                    MarketplaceSessionCookie(
                        name="session-id",
                        value=SecretStr("secret-cookie"),
                    )
                ],
                tokens=[
                    MarketplaceSessionToken(
                        name="x-token",
                        value=SecretStr("secret-token"),
                    )
                ],
                captured_at=NOW,
                region_hint=region_hint,
            ),
        ),
        now=NOW,
    )
    connection.next_sync_at = NOW - timedelta(minutes=1)
    session.commit()
    session.refresh(connection)
    return connection


def _item(
    external_item_id: str = "cart-line-1",
    source_product_id: str | None = "ozon-sku-1",
) -> SanitizedMarketplaceItem:
    return SanitizedMarketplaceItem(
        external_item_id=external_item_id,
        source_product_id=source_product_id,
        product_url=f"https://ozon.ru/product/{external_item_id}",
        title="Test product",
        quantity=2,
        raw_json={"safe": "metadata"},
    )


def test_success_sync_imports_items_tracks_products_and_sets_next_sync(
    db_session: Session,
) -> None:
    connection = _connect_marketplace(db_session)
    cart_adapter = FakeAdapter(MarketplaceSyncAdapterResult.success(items=[_item()]))
    favorites_adapter = FakeAdapter(
        MarketplaceSyncAdapterResult.success(
            items=[_item("fav-line-1", "ozon-sku-fav")]
        )
    )

    report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={
            ("ozon", "cart"): cart_adapter,
            ("ozon", "favorites"): favorites_adapter,
        },
        now=NOW,
        worker_name="unit-test-worker",
    )

    db_session.refresh(connection)
    assert report.processed_connections == 1
    assert report.synced_collections == 2
    assert report.imported_items == 2
    assert report.tracked_products_updated == 2
    assert len(cart_adapter.calls) == 1
    assert len(favorites_adapter.calls) == 1
    assert connection.last_synced_at == NOW.replace(tzinfo=None)
    assert connection.next_sync_at == (NOW + timedelta(seconds=3600)).replace(
        tzinfo=None
    )
    assert connection.next_retry_at is None

    sync_sessions = db_session.scalars(select(MarketplaceSyncSession)).all()
    assert {sync.collection_type for sync in sync_sessions} == {"cart", "favorites"}
    assert {sync.status for sync in sync_sessions} == {"succeeded"}
    assert len(db_session.scalars(select(ImportedItem)).all()) == 2
    assert len(db_session.scalars(select(TrackedProduct)).all()) == 2
    assert len(db_session.scalars(select(UserProductSubscription)).all()) == 2


def test_marketplace_sync_worker_uses_region_hint_without_mixing_imports(
    db_session: Session,
) -> None:
    _connect_marketplace(db_session, scope=["cart_read"], region_hint="msk")
    adapter = FakeAdapter(MarketplaceSyncAdapterResult.success(items=[_item()]))

    first_report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={("ozon", "cart"): adapter},
        now=NOW,
        worker_name="unit-test-worker",
    )

    _connect_marketplace(db_session, scope=["cart_read"], region_hint="spb")
    second_report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={("ozon", "cart"): adapter},
        now=NOW + timedelta(minutes=59),
        worker_name="unit-test-worker",
    )

    collections = db_session.scalars(
        select(ImportedCollection).order_by(ImportedCollection.region_code.asc())
    ).all()
    products = db_session.scalars(
        select(TrackedProduct).order_by(TrackedProduct.region_code.asc())
    ).all()
    subscriptions = db_session.scalars(
        select(UserProductSubscription).order_by(UserProductSubscription.region_code.asc())
    ).all()

    assert first_report.tracked_products_updated == 1
    assert second_report.tracked_products_updated == 1
    assert [
        (item.source, item.collection_type, item.region_code) for item in collections
    ] == [
        ("ozon", "cart", "msk"),
        ("ozon", "cart", "spb"),
    ]
    assert [(item.external_product_id, item.region_code) for item in products] == [
        ("ozon-sku-1", "msk"),
        ("ozon-sku-1", "spb"),
    ]
    assert [item.region_code for item in subscriptions] == ["msk", "spb"]


def test_expired_token_marks_reconnect_required_and_does_not_log_plaintext(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _connect_marketplace(db_session, scope=["cart_read"])
    adapter = FakeAdapter(MarketplaceSyncAdapterResult.failure(reason="login_required"))

    with caplog.at_level(logging.INFO):
        report = sync_due_marketplace_connections(
            db_session,
            adapter_registry={("ozon", "cart"): adapter},
            now=NOW,
            worker_name="unit-test-worker",
        )

    db_session.refresh(connection)
    assert report.failed_collections == 1
    assert connection.status == "reconnect_required"
    assert connection.reconnect_reason == "login_required"
    assert "secret-cookie" not in caplog.text
    assert "secret-token" not in caplog.text


def test_partial_parse_imports_valid_items_and_records_safe_failure(
    db_session: Session,
) -> None:
    _connect_marketplace(db_session, scope=["cart_read"])
    adapter = FakeAdapter(
        MarketplaceSyncAdapterResult.partial(
            items=[_item("valid-line-1", "ozon-sku-valid")],
            reason="partial_parse",
        )
    )

    report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={("ozon", "cart"): adapter},
        now=NOW,
        worker_name="unit-test-worker",
    )

    sync_session = db_session.scalar(select(MarketplaceSyncSession))
    assert report.imported_items == 1
    assert report.failed_collections == 1
    assert sync_session is not None
    assert sync_session.status == "failed"
    assert sync_session.reason == "partial_parse"
    imported_item = db_session.scalar(select(ImportedItem))
    assert imported_item is not None
    assert imported_item.external_item_id == "valid-line-1"


def test_rate_limit_sets_retry_backoff_and_source_cooldown(
    db_session: Session,
) -> None:
    connection = _connect_marketplace(db_session, scope=["cart_read"])
    adapter = FakeAdapter(
        MarketplaceSyncAdapterResult.failure(reason="429", retry_after_seconds=120)
    )

    report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={("ozon", "cart"): adapter},
        now=NOW,
        worker_name="unit-test-worker",
    )

    db_session.refresh(connection)
    quarantine = db_session.scalar(
        select(SourceQuarantineState).where(SourceQuarantineState.source_code == "ozon")
    )
    assert report.failed_collections == 1
    assert connection.status == "sync_failed_retryable"
    assert connection.reconnect_reason == "429"
    assert connection.next_retry_at == (NOW + timedelta(seconds=120)).replace(
        tzinfo=None
    )
    assert connection.next_sync_at == connection.next_retry_at
    assert quarantine is not None
    assert quarantine.status in {"active", "cooldown"}
    assert quarantine.error_type in {None, "http_429"}


def test_no_plaintext_logs_for_successful_sync(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _connect_marketplace(db_session, scope=["cart_read"])
    adapter = FakeAdapter(MarketplaceSyncAdapterResult.success(items=[_item()]))

    with caplog.at_level(logging.INFO):
        sync_due_marketplace_connections(
            db_session,
            adapter_registry={("ozon", "cart"): adapter},
            now=NOW,
            worker_name="unit-test-worker",
        )

    assert "secret-cookie" not in caplog.text
    assert "secret-token" not in caplog.text
    assert "safe" not in caplog.text


def test_kill_switch_and_quarantine_prevent_adapter_calls(
    db_session: Session,
) -> None:
    connection = _connect_marketplace(db_session, scope=["cart_read"])
    source = db_session.scalar(
        select(MarketplaceSessionSource).where(
            MarketplaceSessionSource.marketplace == "ozon"
        )
    )
    assert source is not None
    source.enabled = False
    source.disabled_reason = "source_disabled"
    db_session.add(
        SourceQuarantineState(
            source_code="ozon",
            status="quarantined",
            reason="captcha_detected",
            error_type="captcha_detected",
            quarantined_until=(NOW + timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    db_session.commit()
    adapter = FakeAdapter(MarketplaceSyncAdapterResult.success(items=[_item()]))

    report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={("ozon", "cart"): adapter},
        now=NOW,
        worker_name="unit-test-worker",
    )

    db_session.refresh(connection)
    assert report.processed_connections == 0
    assert report.skipped_connections == 1
    assert adapter.calls == []
    assert connection.status == "source_limited"
    assert connection.reconnect_reason == "source_disabled"


def test_item_without_source_product_id_is_imported_but_not_tracked(
    db_session: Session,
) -> None:
    _connect_marketplace(db_session, scope=["cart_read"])
    adapter = FakeAdapter(
        MarketplaceSyncAdapterResult.success(
            items=[_item("cart-line-without-sku", source_product_id=None)]
        )
    )

    report = sync_due_marketplace_connections(
        db_session,
        adapter_registry={("ozon", "cart"): adapter},
        now=NOW,
        worker_name="unit-test-worker",
    )

    imported_item = db_session.scalar(select(ImportedItem))
    assert report.imported_items == 1
    assert report.tracked_products_updated == 0
    assert imported_item is not None
    assert imported_item.source_product_id is None
    assert db_session.scalars(select(TrackedProduct)).all() == []
    assert db_session.scalars(select(UserProductSubscription)).all() == []
