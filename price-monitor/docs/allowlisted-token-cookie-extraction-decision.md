# Allowlisted Token and Cookie Extraction Decision

Date: 2026-06-15
Status: ADR-first gate, not implementation

## Decision

Price Assistant marketplace connection uses an extension/WebView-style session
connector after the user logs in on the real marketplace page and explicitly
consents to sharing a minimized session bundle.

The connector must extract only source-specific, pre-approved cookie/token names.
No real Ozon, Wildberries, or Yandex Market cookie/token names are approved by
this ADR. Each source remains blocked until legal/security review identifies the
minimum names required for read-only cart/favorites sync and records them in a
follow-up source approval.

The term "OAuth" in current product prompts means "marketplace session connector
after real marketplace login and explicit consent", not password collection, not
raw browser storage export, and not captcha/fingerprint bypass.

## Extraction Rules

- The connector opens only the real marketplace login, cart, or favorites page.
- The user enters credentials only into the marketplace-controlled page.
- The connector may request browser cookie access only for the selected
  marketplace host and only after a user action.
- The connector must call the browser cookies API with narrow host permissions
  and filter by the approved allowlist before building the bundle.
- The connector must never send a cookie/token that is not allowlisted for the
  selected marketplace and scope.
- The connector must not read or transmit marketplace password fields, Savello or
  WordPress auth cookies, browser password-manager data, localStorage dumps,
  sessionStorage dumps, raw HTML, payment data, passport/identity data, or any
  non-product private page content.
- Consent is source-specific and scope-specific. Without consent, no session
  bundle request may be sent to WordPress.

## Existing Contracts

The future connector must use the already implemented public boundary:

- WordPress proxy: `POST /wp-json/cashback/v1/price-assistant/connections`
- WordPress proxy: `POST /wp-json/cashback/v1/price-assistant/connections/{connection_id}/session-bundle`
- FastAPI upstream: `POST /v1/marketplace-connections`
- FastAPI upstream: `POST /v1/marketplace-connections/{connection_id}/session-bundle`

The backend already filters non-allowlisted values before encryption and rejects
bundles that contain no allowlisted values. This ADR does not change that API.

## Source-Specific Gate

Before adding any real allowlist entry for `ozon`, `wildberries`, or
`yandex_market`, create a source approval record that includes:

- exact cookie/token names;
- source page or official API that proves why each value is needed;
- scope mapping: `cart_read`, `favorites_read`, or both;
- host permission pattern;
- retention and expiry behavior;
- legal/ToS reviewer and date;
- security reviewer and date;
- fixture names that prove only approved values are accepted.

If the minimum required names cannot be proven from official documentation,
controlled source analysis, or an approved legal/security review, the source
stays blocked and no names are seeded.

## Required Future Tests

- Allowlist accepts only approved names per marketplace and scope.
- Non-allowlisted cookies/tokens are dropped and never encrypted or sent.
- A bundle without consent is rejected by the WordPress proxy.
- Password/login/localStorage/sessionStorage/raw HTML fields are rejected.
- WordPress/Savello auth cookie names are rejected even if supplied by a client.
- Connector logs, WordPress responses, FastAPI responses, metrics, and admin
  diagnostics never include cookie/token values.
- Browser permission denial produces a safe disconnected or reconnect prompt,
  not a partial secret upload.

## References Checked

- Chrome cookies API requires the `cookies` permission plus host permissions:
  https://developer.chrome.com/docs/extensions/reference/api/cookies
- MDN WebExtensions cookies API requires the `cookies` permission and relevant
  host permissions:
  https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/cookies
- MDN host permissions describe runtime host grants for APIs that read or modify
  host data:
  https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/host_permissions

## Explicit Non-Goals

This ADR does not implement a browser extension, WebView, marketplace adapter,
sync worker, UI, migration, source seed, real cookie/token allowlist, or
marketplace HTTP request.
