# Price Assistant Backend Foundation Decisions

Date: 2026-06-15

## Decision

Implement the backend foundation as an additive FastAPI/MariaDB layer on top of
the existing encrypted marketplace session storage.

This decision keeps the existing public marketplace connection contract intact
and adds only the missing foundation pieces:

- create-only marketplace connection flow;
- separate encrypted session bundle attachment endpoint;
- POST disconnect and reconnect-required aliases;
- idempotent sync sessions and imported cart/favorites/manual/search items;
- local-only product comparison storage and read API;
- admin-managed stores, store sources, import summaries, and diagnostics.

## Security Boundaries

The backend still does not request, receive, store, or replay marketplace
passwords. It accepts only explicit-consent session bundles that pass the
existing allowlist validation and authenticated encryption path.

No real Ozon, Wildberries, or Yandex Market cookie/token names are seeded by
this foundation. Source-specific allowlists remain a separate legal/security
decision.

No marketplace HTTP requests, WebView/extension behavior, captcha bypass,
notification delivery, or worker fetch logic is introduced by this decision.

## Idempotency

New mutating Price Assistant POST endpoints require an `Idempotency-Key` header.
The service stores the request body hash and JSON response by operation scope.
Repeating the same key and body returns the stored response; repeating the same
key with a different body fails with `409 idempotency_key_conflict`.

The existing inline `POST /v1/marketplace-connections` endpoint remains backward
compatible and does not require `Idempotency-Key`.

## Data Model

The foundation adds tables for:

- user regions;
- sync sessions;
- imported collections and items;
- stores and store sources;
- product offers and match groups;
- notification preferences;
- audit events;
- idempotency records.

Existing `marketplace_connections` and `marketplace_session_secrets` are not
renamed. Encrypted bundles continue to use the existing AES-256-GCM envelope
encryption model and redaction rules.

## Comparison Scope

`GET /v1/products/{id}/compare` reads only local `product_offers` records for a
product that belongs to the requesting `site_id + external_user_id`. It does not
fetch external stores or infer product matches at request time.
