# Marketplace ToS and Access Posture Decision

Date: 2026-06-15
Status: ADR-first gate, not implementation

## Decision

Real Ozon, Wildberries, and Yandex Market cart/favorites synchronization is
blocked until each marketplace passes a separate legal/security/source gate.

Price Assistant may only proceed with a marketplace when the planned access
method is explicitly approved. The default state for every marketplace is no-go.

## Current Source Posture

| Marketplace | Current posture | Reason |
| --- | --- | --- |
| Ozon | No-go for consumer cart/favorites adapters | Current checked OAuth material is for Seller API/private or public seller applications, not a confirmed consumer cart/favorites API for Savello users. |
| Wildberries | No-go for seller-portal scraping; unresolved for consumer cart/favorites | Official WB API uses API tokens and states that seller portal integration without WB API is prohibited. No approved consumer cart/favorites API has been recorded. |
| Yandex Market | No-go for OAuth-first design; unresolved for consumer cart/favorites | Partner API documentation recommends API-Key and marks OAuth as outdated. No approved consumer cart/favorites API has been recorded. |

This posture may change only through a follow-up source approval that cites live
official documentation or a legal/security review.

## Allowed Principles

- User authentication happens only on the real marketplace page.
- No marketplace login/password is requested, stored, proxied, or replayed.
- Session values are minimized and allowlisted before upload.
- Backend stores session bundles only through existing encrypted storage.
- `401`, `403`, `login_required`, and `expired` move the connection to
  `reconnect_required`.
- Captcha, bot detection, fingerprint challenge, block, or rate-limit pressure
  stops sync and must not trigger escalation or bypass attempts.
- Each source must have an independent kill switch.

## Forbidden Methods

- Login/password collection in Savello UI, backend, worker, extension, or logs.
- Captcha solving, fingerprint bypass, or access-control circumvention.
- Raw browser profile export.
- Raw cookie dump upload.
- Raw HTML/page snapshot storage for private cart/favorites pages.
- Scraping seller portals where official rules require API usage.
- Continuing sync after auth expiry, forbidden response, login-required page, or
  captcha/block signal.

## Source Approval Requirements

Before any implementation beyond ADR/design for a marketplace:

- legal/ToS review must approve the access method;
- security review must approve the session fields and storage path;
- source owner must define supported pages/APIs and broken-page behavior;
- kill switch and observability must already exist or be planned in the same
  approved implementation;
- tests must use fixtures or fake network by default;
- production enablement must be separately controlled by admin/source flags.

## Required Future Tests

- Source disabled state blocks connection and sync.
- Captcha/block/fingerprint signal does not retry aggressively and does not
  attempt bypass.
- Broken marketplace page produces a safe connector error with no secret logging.
- `401`, `403`, `login_required`, and `expired` produce `reconnect_required`.
- Each marketplace adapter can be disabled independently.
- All network tests use fakes/fixtures until the source gate is approved.

## References Checked

- Ozon Seller API OAuth process:
  https://dev.ozon.ru/start/450-Protsess-OAuth-avtorizatsii-dlia-dostupa-k-Seller-API-Ozon/
- Ozon Seller API key rules and OAuth direction:
  https://dev.ozon.ru/start/454-Novye-pravila-raboty-s-kliuchami-v-Seller-API/
- Wildberries API authorization and seller portal restriction:
  https://dev.wildberries.ru/en/docs/openapi/api-information
- Yandex Market Partner API authorization, API-Key recommendation, OAuth
  outdated status:
  https://yandex.ru/dev/market/partner-api/doc/en/concepts/authorization

## Explicit Non-Goals

This ADR does not approve any source for production, add real adapter code, add
allowlist names, run marketplace HTTP requests, or change public APIs.
