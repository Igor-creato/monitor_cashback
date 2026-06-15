# Reconnect State Machine Decision

Date: 2026-06-15
Status: ADR-first gate, not implementation

## Decision

Price Assistant uses the existing marketplace connection states as the public
status contract for WordPress UI, backend sync, and future marketplace adapters.
This ADR does not add or rename states.

The user-facing labels are:

| Backend status | User-facing label | Meaning |
| --- | --- | --- |
| `connecting` | Connecting | Connection exists but no approved encrypted bundle is attached yet. |
| `connected` | Connected / Sync ok | Encrypted bundle exists and the last known sync state is acceptable. |
| `sync_failed_retryable` | Sync retrying | Temporary failure; worker may retry with backoff. |
| `source_limited` | Source temporarily limited | Marketplace or source-level block/rate/captcha pressure stopped sync. |
| `reconnect_required` | Reconnect required | User action is required because the current session cannot be safely used. |
| `disconnected` | Disconnected | User/admin revoked the connection and active bundle access is deleted. |

`connected` and "sync ok" are display variants over the same backend status.
If `last_synced_at` is present and no retry/reconnect reason exists, UI may show
"sync ok"; otherwise it shows "connected".

## Transition Rules

- Create-only connection sets `connecting`.
- Successful explicit-consent bundle attachment sets `connected`.
- Successful sync finish keeps `connected` and updates sync metadata in the
  existing sync-session flow when implemented.
- Temporary fetch/parser/network failure sets `sync_failed_retryable`.
- Source rate-limit, captcha, block, or source quarantine sets `source_limited`.
- `401`, `403`, `login_required`, and `expired` set `reconnect_required`.
- Disconnect sets `disconnected` and removes active secret access.
- Re-attaching a valid explicit-consent bundle to an owned connection may move
  `reconnect_required` or `disconnected` back to `connected` only through the
  existing attach/connect path.

## Existing Contracts

Current FastAPI endpoints already expose status without secrets:

- `GET /v1/marketplace-connections`
- `POST /v1/marketplace-connections/{connection_id}/disconnect`
- `POST /v1/marketplace-connections/{connection_id}/reconnect-required`
- `POST /v1/sync-sessions/{sync_session_id}/finish`

Current WordPress proxy routes expose the same owner-scoped status:

- `GET /wp-json/cashback/v1/price-assistant/connections`
- `GET /wp-json/cashback/v1/price-assistant/sync-status`
- `DELETE /wp-json/cashback/v1/price-assistant/connections/{connection_id}`

No response may include cookies, tokens, ciphertext, wrapped DEKs, or raw
marketplace page content.

## Required Future Tests

- `401` sets `reconnect_required` with reason `401`.
- `403` sets `reconnect_required` with reason `403`.
- `login_required` sets `reconnect_required` with reason `login_required`.
- `expired` sets `reconnect_required` with reason `expired`.
- Non-auth retryable failures do not set `reconnect_required`.
- Disconnect deletes active secret access and returns `disconnected`.
- UI maps all supported statuses to safe labels and never displays secret
  material.
- Reconnect flow requires a fresh explicit-consent bundle upload.

## Explicit Non-Goals

This ADR does not add new states, migrations, retry scheduler behavior, UI
assets, worker code, or marketplace adapters.
