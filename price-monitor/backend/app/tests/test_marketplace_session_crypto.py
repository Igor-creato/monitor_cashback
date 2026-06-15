from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.db as db
from app.core import config
from app.models.monitoring import (
    MarketplaceConnection,
    MarketplaceSessionAuditEvent,
    MarketplaceSessionSecret,
    MarketplaceSessionSource,
)
from app.services.marketplace_sessions import (
    EncryptionConfigurationError,
    decrypt_session_bundle_for_sync,
    encrypt_session_bundle_for_connection,
    record_marketplace_sync_auth_failure,
)


def _keyring() -> SecretStr:
    return SecretStr("v1:" + base64.b64encode(b"k" * 32).decode())


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


def _connection(session: Session) -> MarketplaceConnection:
    source = MarketplaceSessionSource(marketplace="ozon", enabled=True)
    connection = MarketplaceConnection(
        site_id="savelloclub.ru",
        external_user_id="wp:savelloclub.ru:123",
        marketplace="ozon",
        status="connected",
        scope_json=["cart_read"],
        consent_version="price-assistant-session-v1",
        consented_at=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
    )
    session.add_all([source, connection])
    session.commit()
    return connection


def test_session_bundle_is_encrypted_and_authenticated(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    connection = _connection(db_session)
    plaintext = {
        "cookies": [{"name": "session-id", "value": "secret-cookie"}],
        "tokens": [{"name": "x-token", "value": "secret-token"}],
        "metadata": {"region": "msk"},
    }

    secret = encrypt_session_bundle_for_connection(
        db_session,
        connection,
        plaintext,
        now=datetime(2026, 6, 15, 10, 1, tzinfo=UTC),
    )

    assert secret.key_version == "v1"
    assert secret.encryption_alg == "AES-256-GCM"
    assert "secret-cookie" not in secret.encrypted_cookie_bundle
    assert "secret-token" not in secret.encrypted_cookie_bundle
    assert secret.bundle_fingerprint

    decrypted = decrypt_session_bundle_for_sync(
        db_session,
        connection.id,
        worker_name="sync-worker-1",
        now=datetime(2026, 6, 15, 10, 2, tzinfo=UTC),
    )

    assert decrypted == plaintext
    audit = db_session.scalars(
        select(MarketplaceSessionAuditEvent).order_by(
            MarketplaceSessionAuditEvent.id.asc()
        )
    ).all()
    assert [event.event_type for event in audit] == ["connect", "decrypt_for_sync"]
    assert audit[1].actor_type == "worker"
    assert audit[1].metadata_json == {"worker_name": "sync-worker-1"}


def test_decryption_fails_when_connection_aad_changes(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    connection = _connection(db_session)
    encrypt_session_bundle_for_connection(
        db_session,
        connection,
        {"cookies": [{"name": "session-id", "value": "secret-cookie"}]},
    )
    connection.external_user_id = "wp:savelloclub.ru:attacker"
    db_session.commit()

    with pytest.raises(ValueError, match="session_bundle_decryption_failed"):
        decrypt_session_bundle_for_sync(db_session, connection.id, worker_name="worker")


def test_missing_encryption_config_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", SecretStr(""))
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "")
    connection = _connection(db_session)

    with pytest.raises(EncryptionConfigurationError):
        encrypt_session_bundle_for_connection(
            db_session,
            connection,
            {"cookies": [{"name": "session-id", "value": "secret-cookie"}]},
        )


def test_auth_failure_sets_reconnect_required_and_audits(
    db_session: Session,
) -> None:
    connection = _connection(db_session)

    updated = record_marketplace_sync_auth_failure(
        db_session,
        connection.id,
        reason="login_required",
        now=datetime(2026, 6, 15, 11, 0, tzinfo=UTC),
    )

    assert updated is not None
    assert updated.status == "reconnect_required"
    assert updated.reconnect_reason == "login_required"
    event = db_session.scalar(select(MarketplaceSessionAuditEvent))
    assert event is not None
    assert event.event_type == "reconnect_required"
    assert event.metadata_json == {"reason": "login_required"}


def test_deleted_secret_cannot_be_decrypted(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    connection = _connection(db_session)
    secret = encrypt_session_bundle_for_connection(
        db_session,
        connection,
        {"cookies": [{"name": "session-id", "value": "secret-cookie"}]},
    )
    secret.deleted_at = datetime(2026, 6, 15, 12, 0)
    db_session.commit()

    with pytest.raises(ValueError, match="session_bundle_unavailable"):
        decrypt_session_bundle_for_sync(db_session, connection.id, worker_name="worker")


def test_secret_model_has_no_plaintext_value_columns() -> None:
    column_names = set(MarketplaceSessionSecret.__table__.columns.keys())

    assert "cookie_value" not in column_names
    assert "token_value" not in column_names
    assert "plaintext" not in column_names
