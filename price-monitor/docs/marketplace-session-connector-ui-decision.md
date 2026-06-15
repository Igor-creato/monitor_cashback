# Marketplace Session Connector UI Decision

Date: 2026-06-15
Status: ADR-first gate, not implementation

## Decision

The user account UI will present one independent connection control for each
marketplace: Ozon, Wildberries, and Yandex Market.

Each button starts a connector handoff that opens the real marketplace login,
cart, or favorites page in the extension/WebView-controlled browser context. The
Savello page never asks for a marketplace login or password.

This ADR records the intended UI and handoff contract only. It does not add
WordPress templates, JS assets, extension code, or WebView code.

## UI Behavior

- Show one row/button per marketplace.
- Show status per marketplace: `connected`, `sync ok`, `reconnect required`, or
  `disconnected`.
- If marketplace feature flag is disabled in WordPress, show disabled/unavailable
  state and do not start connection.
- On connect/reconnect click:
  - call WordPress `POST /price-assistant/connections` to create or refresh a
    connection;
  - hand off `{connection_id, marketplace, consent_version, scope}` to the
    connector;
  - connector opens the real marketplace page;
  - connector extracts only allowlisted values after user action and consent;
  - connector uploads the bundle through WordPress session-bundle endpoint.
- On disconnect click, call the existing WordPress disconnect endpoint.
- On permission denial, broken page, captcha/block, or missing allowlisted values,
  show a safe error and do not upload partial secrets.

## Connector Handoff Contract

The UI may pass only:

- `connection_id`;
- `marketplace`;
- `consent_version`;
- `scope`;
- WordPress REST base URL and nonce already used for authenticated proxy calls;
- connector/client version.

The UI must not pass marketplace credentials, raw cookies, raw browser storage,
FastAPI HMAC secrets, or internal backend URLs.

## Consent Boundary

Consent text must be shown after the user is authenticated on the real
marketplace page and before upload to WordPress. The consent must name the
marketplace and scopes, and explain that cart/favorites will be synchronized.

No consent means no upload. Closing the connector window, denying host
permissions, or failing to find allowlisted values must leave the connection in
`connecting`, `disconnected`, or a safe retryable UI state without secrets.

## Required Future Tests

- Three marketplace buttons render with independent enabled/disabled flags.
- Create connection request is owner-scoped and does not accept client-forged
  `external_user_id`.
- Session bundle upload requires explicit consent.
- Connector handoff does not expose HMAC secret or backend URL.
- Status mapping covers `connected`, `sync ok`, `reconnect required`, and
  `disconnected`.
- Broken marketplace page shows safe error and uploads no bundle.
- Permission denial uploads no bundle.

## Existing Contracts

- WordPress consent metadata:
  `GET /wp-json/cashback/v1/price-assistant/consent`
- WordPress connections:
  `GET|POST /wp-json/cashback/v1/price-assistant/connections`
- WordPress session bundle:
  `POST /wp-json/cashback/v1/price-assistant/connections/{connection_id}/session-bundle`
- WordPress disconnect:
  `DELETE /wp-json/cashback/v1/price-assistant/connections/{connection_id}`

## Explicit Non-Goals

This ADR does not implement the account UI, extension/WebView, marketplace page
automation, allowlist names, import worker, or adapter code.
