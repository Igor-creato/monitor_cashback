# Session Bundle Storage and Encryption Decision

Date: 2026-06-15

## Decision

Marketplace session bundles are stored only as AES-256-GCM authenticated
ciphertext. The service uses the existing `cryptography` package and envelope
encryption: each bundle gets a random 256-bit DEK, the bundle ciphertext is
authenticated with connection-scoped AAD, and the DEK is wrapped by the active
KEK from `MARKETPLACE_SESSION_KEYRING`.

The keyring env contract remains:

```text
MARKETPLACE_SESSION_KEYRING=v1:<base64-32-byte-key>[,v2:<base64-32-byte-key>]
MARKETPLACE_SESSION_ACTIVE_KEY_VERSION=v2
```

The active version is the primary key for new writes and rewrap operations.
Other configured versions are previous keys for decrypting existing secrets.

## Payload Format

`marketplace_session_secrets.payload_format_version` records the encrypted
payload shape. Existing direct service-layer payloads remain legacy format `1`.
New API marketplace bundles use format `2`:

- `format_version`;
- `marketplace`;
- allowlisted `cookies`;
- allowlisted `tokens`;
- `captured_at`;
- optional `user_agent_hint`;
- optional `region_hint`.

Cookie/token values are represented as secret Pydantic fields before encryption.
They are extracted only inside the service layer and must not appear in repr,
logs, metrics, admin responses, or API responses.

## Filtering and Fail-Closed Rules

The backend rejects prohibited fields such as marketplace passwords,
local/session storage dumps, raw HTML, payment data, and WordPress/WooCommerce
session names. Non-allowlisted cookie/token names are dropped before encryption.
If no allowlisted values remain, the request is rejected.

## Rotation

Rotation is service-layer only. `rotate_session_secret_key_for_connection()`
unwraps the DEK with the row's current key version, rewraps it with the active
primary key, updates `key_version`/`rotated_at`, and audits `rotation`. It does
not return plaintext and does not add public API behavior.

## Disconnect and Deletion

Disconnect renders the stored bundle cryptographically unavailable. The service
sets `deleted_at`, clears the stored ciphertext, wrapped DEK, nonce, and tag,
replaces AAD with `{"deleted": true}`, and stores only a non-secret deletion
fingerprint. Responses and admin diagnostics continue to expose only status,
key version, and `has_secret`; they never return ciphertext or wrapped DEKs.

## Explicit Non-Goals

This decision does not add real Ozon/Wildberries/Yandex Market allowlist names,
WebView/extension behavior, marketplace HTTP requests, sync worker logic,
captcha bypass, notification delivery, or WordPress changes.
