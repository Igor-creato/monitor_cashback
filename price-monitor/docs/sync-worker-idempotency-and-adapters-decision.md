# Sync Worker Idempotency and Adapters Decision

Date: 2026-06-15
Status: ADR-first gate, not implementation

## Decision

Future cart/favorites sync must use the existing encrypted session bundle and
sync-session foundation. Worker/adapters remain blocked until source-specific
legal/security approval and fixture-based contracts exist.

Immediate import from the connector is allowed only as sanitized product item
data sent through the existing WordPress/FastAPI sync-session flow. It must not
include raw marketplace HTML, raw cookies, raw tokens, private non-product page
data, payment data, or user identity documents.

## Adapter Boundary

Each marketplace adapter must be a separate implementation for:

- `ozon` cart;
- `ozon` favorites;
- `wildberries` cart;
- `wildberries` favorites;
- `yandex_market` cart;
- `yandex_market` favorites.

No adapter may be enabled in production until the source gate approves the access
method and allowlist. Adapter tests must default to fixtures/fake network.

## Idempotency Model

Future worker/import writes must be idempotent by:

- `site_id`;
- `external_user_id`;
- `connection_id`;
- `marketplace`;
- collection type: `cart` or `favorites`;
- marketplace item identity;
- observation timestamp or sync window;
- idempotency key for mutating API calls.

The current foundation already supports:

- `POST /v1/sync-sessions`;
- `POST /v1/sync-sessions/{sync_session_id}/items`;
- `POST /v1/sync-sessions/{sync_session_id}/finish`;
- owner-scoped `GET /v1/collections`.

Future implementation should reuse these contracts instead of adding a parallel
import API.

## Broken Page and Failure Behavior

- Broken marketplace page: fail the sync/import safely with a non-secret reason.
- Missing expected allowlisted values: do not upload bundle; show reconnect or
  connector error.
- `401`, `403`, `login_required`, `expired`: set `reconnect_required`.
- Captcha/block/fingerprint challenge: stop, do not bypass, and mark source as
  limited or blocked according to the approved source policy.
- Parser drift: fail the adapter and keep previous imported collection intact
  unless the approved implementation explicitly defines replacement behavior.

## Sanitized Immediate Import Shape

Sanitized items may include only:

- stable marketplace item id;
- source product id or SKU when available;
- product URL;
- title;
- quantity;
- optional source metadata that contains no secrets and no raw private page data.

If a field is not available without reading private raw page content, omit the
field rather than inventing it.

## Required Future Tests

- Duplicate sync runs do not duplicate imported items.
- Duplicate item upload with the same idempotency key returns the stored response.
- Same item observed twice updates the item instead of creating another row.
- Broken marketplace page produces safe failure and no secret logging.
- `401`, `403`, `login_required`, and `expired` set `reconnect_required`.
- Captcha/block/fingerprint challenge does not trigger bypass.
- Immediate sanitized import uses existing sync-session/items endpoints.
- Ozon/WB/YandexMarket adapters run only against fixtures/fake network until
  source gates pass.

## Explicit Non-Goals

This ADR does not add worker tasks, Celery schedules, marketplace adapters,
fixture files, network code, parser code, migrations, or public API changes.
