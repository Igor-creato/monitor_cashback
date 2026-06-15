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
    MarketplaceSessionAllowlist,
    MarketplaceSessionAuditEvent,
    MarketplaceSessionSecret,
    MarketplaceSessionSource,
)
from app.schemas.marketplace_sessions import MarketplaceConnectionCreate
from app.services import marketplace_sessions as marketplace_session_service
from app.services.marketplace_sessions import (
    EncryptionConfigurationError,
    connect_marketplace_session,
    decrypt_session_bundle_for_sync,
    encrypt_session_bundle_for_connection,
    record_marketplace_sync_auth_failure,
)


def _keyring() -> SecretStr:
    return SecretStr("v1:" + base64.b64encode(b"k" * 32).decode())


def _dual_keyring() -> SecretStr:
    return SecretStr(
        "v1:"
        + base64.b64encode(b"k" * 32).decode()
        + ",v2:"
        + base64.b64encode(b"p" * 32).decode()
    )


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


def _enable_allowlist(session: Session) -> None:
    session.add(MarketplaceSessionSource(marketplace="ozon", enabled=True))
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


def test_v2_payload_filters_non_allowlisted_values_and_redacts_repr(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    _enable_allowlist(db_session)
    request = MarketplaceConnectionCreate(
        site_id="savelloclub.ru",
        external_user_id="wp:savelloclub.ru:123",
        marketplace="ozon",
        consent_version="price-assistant-session-v1",
        scope=["cart_read", "favorites_read"],
        captured_at=datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
        connector_version="0.1.0",
        session_bundle={
            "cookies": [
                {
                    "name": "session-id",
                    "value": "secret-cookie",
                    "domain": ".ozon.ru",
                    "path": "/",
                    "expires": "2026-06-16T10:00:00Z",
                    "secure": True,
                    "httpOnly": True,
                    "sameSite": "Lax",
                },
                {
                    "name": "analytics-id",
                    "value": "drop-me",
                    "domain": ".ozon.ru",
                    "path": "/",
                    "expires": None,
                    "secure": True,
                    "httpOnly": False,
                    "sameSite": "Lax",
                },
            ],
            "tokens": [
                {
                    "name": "x-token",
                    "value": "secret-token",
                    "expires": "2026-06-16T10:00:00Z",
                },
                {"name": "unused-token", "value": "drop-token", "expires": None},
            ],
            "captured_at": "2026-06-15T10:00:00Z",
            "user_agent_hint": "desktop-chromium",
            "region_hint": "msk",
        },
    )

    assert "secret-cookie" not in repr(request.session_bundle)
    assert "secret-token" not in repr(request.session_bundle)

    connection = connect_marketplace_session(db_session, request)
    secret = db_session.scalar(select(MarketplaceSessionSecret))
    assert secret is not None
    assert secret.payload_format_version == 2

    decrypted = decrypt_session_bundle_for_sync(
        db_session,
        connection.id,
        worker_name="sync-worker-1",
    )

    assert decrypted == {
        "format_version": 2,
        "marketplace": "ozon",
        "cookies": [
            {
                "name": "session-id",
                "value": "secret-cookie",
                "domain": ".ozon.ru",
                "path": "/",
                "expires": "2026-06-16T10:00:00Z",
                "secure": True,
                "httpOnly": True,
                "sameSite": "Lax",
            }
        ],
        "tokens": [
            {
                "name": "x-token",
                "value": "secret-token",
                "expires": "2026-06-16T10:00:00Z",
            }
        ],
        "captured_at": "2026-06-15T10:00:00Z",
        "user_agent_hint": "desktop-chromium",
        "region_hint": "msk",
    }


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


def test_decryption_fails_with_wrong_previous_key(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _dual_keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    connection = _connection(db_session)
    encrypt_session_bundle_for_connection(
        db_session,
        connection,
        {"cookies": [{"name": "session-id", "value": "secret-cookie"}]},
    )
    wrong_v1_keyring = SecretStr(
        "v1:"
        + base64.b64encode(b"w" * 32).decode()
        + ",v2:"
        + base64.b64encode(b"p" * 32).decode()
    )
    monkeypatch.setattr(
        config.settings, "marketplace_session_keyring", wrong_v1_keyring
    )
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v2")

    with pytest.raises(ValueError, match="session_bundle_decryption_failed"):
        decrypt_session_bundle_for_sync(db_session, connection.id, worker_name="worker")


def test_decryption_fails_when_ciphertext_tag_or_wrapped_dek_is_tampered(
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

    for field_name in ("encrypted_cookie_bundle", "tag", "dek_ciphertext"):
        original = getattr(secret, field_name)
        setattr(secret, field_name, base64.b64encode(b"tampered").decode())
        db_session.commit()
        with pytest.raises(ValueError, match="session_bundle_decryption_failed"):
            decrypt_session_bundle_for_sync(
                db_session,
                connection.id,
                worker_name="worker",
            )
        setattr(secret, field_name, original)
        db_session.commit()


def test_previous_key_decrypts_after_primary_changes(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _dual_keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    connection = _connection(db_session)
    encrypt_session_bundle_for_connection(
        db_session,
        connection,
        {"cookies": [{"name": "session-id", "value": "secret-cookie"}]},
    )
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v2")

    decrypted = decrypt_session_bundle_for_sync(
        db_session,
        connection.id,
        worker_name="worker",
    )

    assert decrypted == {"cookies": [{"name": "session-id", "value": "secret-cookie"}]}


def test_rotation_rewraps_active_secret_without_plaintext_export(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    monkeypatch.setattr(config.settings, "marketplace_session_keyring", _dual_keyring())
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v1")
    connection = _connection(db_session)
    secret = encrypt_session_bundle_for_connection(
        db_session,
        connection,
        {"cookies": [{"name": "session-id", "value": "secret-cookie"}]},
    )
    original_ciphertext = secret.encrypted_cookie_bundle
    original_nonce = secret.nonce
    original_tag = secret.tag
    monkeypatch.setattr(config.settings, "marketplace_session_active_key_version", "v2")

    rotated = marketplace_session_service.rotate_session_secret_key_for_connection(
        db_session,
        connection.id,
        actor_type="system",
        now=datetime(2026, 6, 15, 13, 0, tzinfo=UTC),
    )

    assert rotated is not None
    assert rotated.key_version == "v2"
    assert rotated.rotated_at == datetime(2026, 6, 15, 13, 0)
    assert rotated.encrypted_cookie_bundle == original_ciphertext
    assert rotated.nonce == original_nonce
    assert rotated.tag == original_tag
    assert "secret-cookie" not in repr(rotated)
    decrypted = decrypt_session_bundle_for_sync(
        db_session,
        connection.id,
        worker_name="worker",
    )
    assert decrypted == {"cookies": [{"name": "session-id", "value": "secret-cookie"}]}
    events = [
        event.event_type
        for event in db_session.scalars(
            select(MarketplaceSessionAuditEvent).order_by(
                MarketplaceSessionAuditEvent.id.asc()
            )
        )
    ]
    assert "rotation" in events


def test_secret_model_has_no_plaintext_value_columns() -> None:
    column_names = set(MarketplaceSessionSecret.__table__.columns.keys())

    assert "cookie_value" not in column_names
    assert "token_value" not in column_names
    assert "plaintext" not in column_names
    assert "payload_format_version" in column_names
