from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.monitoring import (
    MarketplaceConnection,
    MarketplaceSessionAllowlist,
    MarketplaceSessionAuditEvent,
    MarketplaceSessionSecret,
    MarketplaceSessionSource,
)
from app.schemas.marketplace_sessions import (
    MarketplaceConnectionCreate,
    MarketplaceConnectionStatusResponse,
    MarketplaceSessionBundle,
)

ENCRYPTION_ALG = "AES-256-GCM"
NONCE_BYTES = 12
GCM_TAG_BYTES = 16
MAX_BUNDLE_BYTES = 16 * 1024
PROHIBITED_BUNDLE_FIELDS = frozenset(
    {
        "password",
        "login",
        "username",
        "localStorage",
        "sessionStorage",
        "html",
        "payment",
        "passport",
    }
)
AUTH_FAILURE_REASONS = frozenset({"401", "403", "login_required", "expired"})


class EncryptionConfigurationError(RuntimeError):
    pass


class MarketplaceSessionError(ValueError):
    detail: str

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class MarketplaceDisabledError(MarketplaceSessionError):
    pass


def current_utc_datetime() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _Keyring:
    active_version: str
    keys: dict[str, bytes]

    def active_key(self) -> bytes:
        key = self.keys.get(self.active_version)
        if key is None:
            raise EncryptionConfigurationError("active_key_version_not_configured")
        return key

    def key_for_version(self, key_version: str) -> bytes:
        key = self.keys.get(key_version)
        if key is None:
            raise EncryptionConfigurationError("key_version_not_configured")
        return key


def connect_marketplace_session(
    session: Session,
    request: MarketplaceConnectionCreate,
    *,
    now: datetime | None = None,
) -> MarketplaceConnection:
    now = _as_utc_naive(now or current_utc_datetime())
    _validate_bundle_contract(request.session_bundle)
    source = _get_marketplace_source(session, request.marketplace)
    if source is None:
        raise MarketplaceSessionError("marketplace_unknown")
    if not source.enabled:
        _audit_event(
            session,
            connection=None,
            site_id=request.site_id,
            external_user_id=request.external_user_id,
            marketplace=request.marketplace,
            event_type="kill_switch_blocked",
            actor_type="user",
            metadata={"reason": source.disabled_reason},
            now=now,
        )
        session.commit()
        raise MarketplaceDisabledError("marketplace_disabled")

    _validate_allowlisted_bundle(session, request)
    connection = _get_connection(
        session,
        site_id=request.site_id,
        external_user_id=request.external_user_id,
        marketplace=request.marketplace,
    )
    if connection is None:
        connection = MarketplaceConnection(
            site_id=request.site_id,
            external_user_id=request.external_user_id,
            marketplace=request.marketplace,
            status="connected",
            scope_json=request.scope,
            consent_version=request.consent_version,
            consented_at=_as_utc_naive(request.captured_at),
            expires_at=_as_utc_naive_or_none(request.expires_at),
        )
        session.add(connection)
        session.flush()
    else:
        connection.status = "connected"
        connection.scope_json = request.scope
        connection.consent_version = request.consent_version
        connection.consented_at = _as_utc_naive(request.captured_at)
        connection.expires_at = _as_utc_naive_or_none(request.expires_at)
        connection.reconnect_reason = None
        connection.next_retry_at = None
        connection.kill_switch_blocked_at = None
        _delete_active_secrets(session, connection, now=now)

    encrypt_session_bundle_for_connection(
        session,
        connection,
        _bundle_to_plain_dict(request.session_bundle),
        now=now,
        commit=False,
    )
    session.commit()
    session.refresh(connection)
    return connection


def list_marketplace_connections(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
) -> list[MarketplaceConnectionStatusResponse]:
    connections = session.scalars(
        select(MarketplaceConnection)
        .where(
            MarketplaceConnection.site_id == site_id,
            MarketplaceConnection.external_user_id == external_user_id,
        )
        .order_by(MarketplaceConnection.id.asc())
    )
    return [_serialize_connection(connection) for connection in connections]


def disconnect_marketplace_connection(
    session: Session,
    *,
    connection_id: int,
    site_id: str,
    external_user_id: str,
    now: datetime | None = None,
) -> MarketplaceConnection | None:
    now = _as_utc_naive(now or current_utc_datetime())
    connection = session.scalar(
        select(MarketplaceConnection).where(
            MarketplaceConnection.id == connection_id,
            MarketplaceConnection.site_id == site_id,
            MarketplaceConnection.external_user_id == external_user_id,
        )
    )
    if connection is None:
        return None

    connection.status = "disconnected"
    connection.next_retry_at = None
    connection.reconnect_reason = None
    _audit_event(
        session,
        connection=connection,
        event_type="disconnect",
        actor_type="user",
        metadata=None,
        now=now,
    )
    _delete_active_secrets(session, connection, now=now)
    session.commit()
    session.refresh(connection)
    return connection


def encrypt_session_bundle_for_connection(
    session: Session,
    connection: MarketplaceConnection,
    bundle: dict[str, Any],
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> MarketplaceSessionSecret:
    now = _as_utc_naive(now or current_utc_datetime())
    keyring = _load_keyring()
    key_version = keyring.active_version
    dek = AESGCM.generate_key(bit_length=256)
    plaintext = _canonical_json_bytes(bundle)
    aad_json = _connection_aad(connection, key_version)
    aad = _canonical_json_bytes(aad_json)

    nonce = os.urandom(NONCE_BYTES)
    ciphertext_with_tag = AESGCM(dek).encrypt(nonce, plaintext, aad)
    ciphertext = ciphertext_with_tag[:-GCM_TAG_BYTES]
    tag = ciphertext_with_tag[-GCM_TAG_BYTES:]

    wrapped_dek = _wrap_dek(dek, keyring.active_key(), key_version, connection.id)
    secret = MarketplaceSessionSecret(
        connection=connection,
        encrypted_cookie_bundle=_b64encode(ciphertext),
        dek_ciphertext=_b64encode(wrapped_dek),
        nonce=_b64encode(nonce),
        tag=_b64encode(tag),
        aad_json=aad_json,
        key_version=key_version,
        encryption_alg=ENCRYPTION_ALG,
        bundle_fingerprint=hashlib.sha256(ciphertext + tag).hexdigest(),
        created_at=now,
    )
    session.add(secret)
    _audit_event(
        session,
        connection=connection,
        event_type="connect",
        actor_type="user",
        metadata={"key_version": key_version},
        now=now,
    )
    if commit:
        session.commit()
        session.refresh(secret)
    else:
        session.flush()
    return secret


def decrypt_session_bundle_for_sync(
    session: Session,
    connection_id: int,
    *,
    worker_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = _as_utc_naive(now or current_utc_datetime())
    connection = session.scalar(
        select(MarketplaceConnection)
        .options(joinedload(MarketplaceConnection.secrets))
        .where(MarketplaceConnection.id == connection_id)
    )
    if connection is None:
        raise ValueError("session_bundle_unavailable")
    if connection.status in {"disconnected", "reconnect_required", "source_limited"}:
        raise ValueError("session_bundle_unavailable")
    secret = _active_secret(connection)
    if secret is None:
        raise ValueError("session_bundle_unavailable")

    try:
        keyring = _load_keyring()
        kek = keyring.key_for_version(secret.key_version)
        dek = _unwrap_dek(
            _b64decode(secret.dek_ciphertext),
            kek,
            secret.key_version,
            connection.id,
        )
        aad = _canonical_json_bytes(_connection_aad(connection, secret.key_version))
        ciphertext_with_tag = _b64decode(secret.encrypted_cookie_bundle) + _b64decode(
            secret.tag
        )
        plaintext = AESGCM(dek).decrypt(
            _b64decode(secret.nonce),
            ciphertext_with_tag,
            aad,
        )
    except (EncryptionConfigurationError, InvalidTag, ValueError) as exc:
        raise ValueError("session_bundle_decryption_failed") from exc

    _audit_event(
        session,
        connection=connection,
        event_type="decrypt_for_sync",
        actor_type="worker",
        metadata={"worker_name": worker_name},
        now=now,
    )
    session.commit()
    return json.loads(plaintext.decode())


def record_marketplace_sync_auth_failure(
    session: Session,
    connection_id: int,
    *,
    reason: str,
    now: datetime | None = None,
) -> MarketplaceConnection | None:
    now = _as_utc_naive(now or current_utc_datetime())
    connection = session.get(MarketplaceConnection, connection_id)
    if connection is None:
        return None

    if reason in AUTH_FAILURE_REASONS:
        connection.status = "reconnect_required"
        event_type = "reconnect_required"
    else:
        connection.status = "sync_failed_retryable"
        event_type = "sync_auth_failure"
    connection.reconnect_reason = reason
    connection.last_validated_at = now
    _audit_event(
        session,
        connection=connection,
        event_type=event_type,
        actor_type="worker",
        metadata={"reason": reason},
        now=now,
    )
    session.commit()
    session.refresh(connection)
    return connection


def serialize_marketplace_connection(
    connection: MarketplaceConnection,
) -> MarketplaceConnectionStatusResponse:
    return _serialize_connection(connection)


def _serialize_connection(
    connection: MarketplaceConnection,
) -> MarketplaceConnectionStatusResponse:
    return MarketplaceConnectionStatusResponse(
        connection_id=connection.id,
        marketplace=connection.marketplace,
        status=connection.status,
        last_validated_at=connection.last_validated_at,
        last_synced_at=connection.last_synced_at,
        next_retry_at=connection.next_retry_at,
        reason=connection.reconnect_reason,
    )


def _load_keyring() -> _Keyring:
    raw = settings.marketplace_session_keyring.get_secret_value().strip()
    active_version = settings.marketplace_session_active_key_version.strip()
    if raw == "" or active_version == "":
        raise EncryptionConfigurationError("marketplace_session_keyring_missing")

    keys: dict[str, bytes] = {}
    for entry in raw.split(","):
        if ":" not in entry:
            raise EncryptionConfigurationError("invalid_keyring_entry")
        version, encoded_key = entry.split(":", 1)
        version = version.strip()
        if version == "":
            raise EncryptionConfigurationError("invalid_keyring_entry")
        try:
            key = base64.b64decode(encoded_key.strip(), validate=True)
        except ValueError as exc:
            raise EncryptionConfigurationError("invalid_keyring_key") from exc
        if len(key) != 32:
            raise EncryptionConfigurationError("invalid_keyring_key_length")
        keys[version] = key

    keyring = _Keyring(active_version=active_version, keys=keys)
    keyring.active_key()
    return keyring


def _wrap_dek(
    dek: bytes,
    kek: bytes,
    key_version: str,
    connection_id: int,
) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    aad = _dek_wrap_aad(key_version, connection_id)
    return nonce + AESGCM(kek).encrypt(nonce, dek, aad)


def _unwrap_dek(
    wrapped_dek: bytes,
    kek: bytes,
    key_version: str,
    connection_id: int,
) -> bytes:
    nonce = wrapped_dek[:NONCE_BYTES]
    ciphertext_with_tag = wrapped_dek[NONCE_BYTES:]
    return AESGCM(kek).decrypt(
        nonce,
        ciphertext_with_tag,
        _dek_wrap_aad(key_version, connection_id),
    )


def _dek_wrap_aad(key_version: str, connection_id: int) -> bytes:
    return _canonical_json_bytes(
        {
            "purpose": "marketplace_session_dek",
            "key_version": key_version,
            "connection_id": connection_id,
        }
    )


def _connection_aad(
    connection: MarketplaceConnection,
    key_version: str,
) -> dict[str, Any]:
    return {
        "connection_id": connection.id,
        "site_id": connection.site_id,
        "external_user_id": connection.external_user_id,
        "marketplace": connection.marketplace,
        "scope": connection.scope_json,
        "consent_version": connection.consent_version,
        "key_version": key_version,
    }


def _validate_bundle_contract(bundle: MarketplaceSessionBundle) -> None:
    extra_fields = set(bundle.model_extra or {})
    if extra_fields & PROHIBITED_BUNDLE_FIELDS:
        raise MarketplaceSessionError("prohibited_session_field")
    payload = _bundle_to_plain_dict(bundle)
    if len(_canonical_json_bytes(payload)) > MAX_BUNDLE_BYTES:
        raise MarketplaceSessionError("session_bundle_too_large")
    for item in [*bundle.cookies, *bundle.tokens]:
        normalized_name = item.name.lower()
        if "password" in normalized_name or normalized_name.startswith(
            ("wp_", "wordpress", "woocommerce")
        ):
            raise MarketplaceSessionError("prohibited_session_field")


def _validate_allowlisted_bundle(
    session: Session,
    request: MarketplaceConnectionCreate,
) -> None:
    allowlist_items = list(
        session.scalars(
            select(MarketplaceSessionAllowlist).where(
                MarketplaceSessionAllowlist.marketplace == request.marketplace,
                MarketplaceSessionAllowlist.enabled.is_(True),
                MarketplaceSessionAllowlist.scope.in_(request.scope),
            )
        )
    )
    if not allowlist_items:
        raise MarketplaceSessionError("session_allowlist_empty")

    allowed = {
        (item.kind, item.scope, item.name)
        for item in allowlist_items
        if item.scope in request.scope
    }
    for cookie in request.session_bundle.cookies:
        if not any(
            ("cookie", scope, cookie.name) in allowed for scope in request.scope
        ):
            raise MarketplaceSessionError("session_value_not_allowlisted")
    for token in request.session_bundle.tokens:
        if not any(("token", scope, token.name) in allowed for scope in request.scope):
            raise MarketplaceSessionError("session_value_not_allowlisted")


def _get_marketplace_source(
    session: Session,
    marketplace: str,
) -> MarketplaceSessionSource | None:
    return session.scalar(
        select(MarketplaceSessionSource).where(
            MarketplaceSessionSource.marketplace == marketplace
        )
    )


def _get_connection(
    session: Session,
    *,
    site_id: str,
    external_user_id: str,
    marketplace: str,
) -> MarketplaceConnection | None:
    return session.scalar(
        select(MarketplaceConnection).where(
            MarketplaceConnection.site_id == site_id,
            MarketplaceConnection.external_user_id == external_user_id,
            MarketplaceConnection.marketplace == marketplace,
        )
    )


def _delete_active_secrets(
    session: Session,
    connection: MarketplaceConnection,
    *,
    now: datetime,
) -> None:
    active_secrets = session.scalars(
        select(MarketplaceSessionSecret).where(
            MarketplaceSessionSecret.connection_id == connection.id,
            MarketplaceSessionSecret.deleted_at.is_(None),
        )
    )
    deleted = False
    for secret in active_secrets:
        secret.deleted_at = now
        deleted = True
    if deleted:
        _audit_event(
            session,
            connection=connection,
            event_type="delete",
            actor_type="user",
            metadata=None,
            now=now,
        )


def _active_secret(
    connection: MarketplaceConnection,
) -> MarketplaceSessionSecret | None:
    active = [secret for secret in connection.secrets if secret.deleted_at is None]
    if not active:
        return None
    return sorted(active, key=lambda item: item.id, reverse=True)[0]


def _audit_event(
    session: Session,
    *,
    connection: MarketplaceConnection | None,
    event_type: str,
    actor_type: str,
    metadata: dict[str, Any] | None,
    now: datetime,
    site_id: str | None = None,
    external_user_id: str | None = None,
    marketplace: str | None = None,
) -> None:
    session.add(
        MarketplaceSessionAuditEvent(
            connection=connection,
            site_id=site_id or (connection.site_id if connection else ""),
            external_user_id=external_user_id
            or (connection.external_user_id if connection else ""),
            marketplace=marketplace or (connection.marketplace if connection else ""),
            event_type=event_type,
            actor_type=actor_type,
            metadata_json=metadata,
            created_at=now,
        )
    )


def _bundle_to_plain_dict(bundle: MarketplaceSessionBundle) -> dict[str, Any]:
    return bundle.model_dump(mode="json")


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode()


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode(), validate=True)


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _as_utc_naive_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _as_utc_naive(value)
