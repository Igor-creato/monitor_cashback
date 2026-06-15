# Monitor Cashback Price Assistant — Product + Risk Spec

**Status:** Product + Risk Spec, planning artifact only
**Date:** 2026-06-15
**Repository:** `F:\cash-back\monitor_cashback`
**Service:** `price-monitor` / Monitor Cashback
**Implementation status:** not implemented unless explicitly listed as current state

## 1. Executive Summary

Monitor Cashback Price Assistant is a cashback-aware price assistant for Savello
Club users. The product combines price monitoring, marketplace cart/favorites
synchronization, cross-store comparison, cashback-aware effective price, and
alerts when a better buying moment appears.

The planned product is similar in user value to YoloPrice/Cheaper-style price
tracking and comparison, but it must follow stricter security boundaries:

- the service must not request, receive, store, or replay marketplace passwords;
- users authenticate only on real Ozon, Wildberries, or Yandex Market pages;
- WebView/extension clients may extract only allowlisted session cookies/tokens;
- session bundles are sent to the backend only after explicit user consent;
- backend storage for session bundles must be encrypted at rest;
- sync workers use encrypted session bundles to refresh cart/favorites data;
- expired, forbidden, or login-required sessions move to `reconnect_required`;
- no captcha bypass or prohibited access escalation is part of the product.

This document defines product scope, production model, risks, roadmap, go/no-go
gates, and ADR backlog. It does not implement code, migrations, tests, APIs,
browser extension behavior, WebView behavior, or marketplace adapters.

## 2. Current State

The existing `price-monitor` backend already has a FastAPI foundation for manual
tracking and internal operations:

- HMAC-protected service-to-service requests from WordPress;
- watchlist CRUD and watchlist UI endpoints;
- price history and price chart endpoints;
- product card response data with local cashback snapshot support;
- fetch jobs, Celery beat scheduling, source health, source quarantine/cooldown,
  proxy pool/cost controls, fetch attempts, cleanup tasks, and Prometheus metrics;
- internal admin diagnostics protected by `ADMIN_API_KEY`;
- demo/test URL normalizer support only for local test sources.

The following capabilities are planned and not implemented by this spec:

- WebView or browser extension session connector;
- encrypted marketplace session bundle storage;
- automatic cart/favorites sync worker;
- real Ozon/WB/YandexMarket URL normalizers and adapters;
- admin-managed cross-store comparison;
- user-facing Price Assistant UI;
- notification delivery for target price, new minimum, and cheaper alternatives;
- ADR files for the decisions listed in this document.

## 3. Product Vision

Price Assistant helps a logged-in Savello Club user decide where and when to buy.
It should answer:

- "Has this product become cheaper?"
- "Is it cheaper on another admin-approved store?"
- "Is it in stock in my region?"
- "What is the delivery impact?"
- "What is the cashback-aware effective price?"
- "Should I wait, buy now, or reconnect my marketplace account?"

Primary user-facing functions:

- monitor price by product link;
- automatically synchronize cart/favorites from Ozon, Wildberries, and Yandex
  Market after explicit user consent;
- search products across stores added and enabled by an admin;
- compare price, availability, region, delivery, cashback, and effective price;
- show a personal account area with tracked products, sync status, charts, and
  alert settings;
- notify users about target price, price drop, new historical minimum, and a
  cheaper comparable product.

Admin-facing functions:

- manage stores and sources eligible for tracking/comparison;
- enable, disable, or quarantine sources;
- review fetch health, source instability, costs, and blocked syncs;
- define comparison eligibility and source risk level;
- monitor consent, reconnect, sync failure, and alert delivery metrics.

## 4. Core Product Capabilities

### 4.1 Price Monitoring by Link

User pastes a product link in the personal account. WordPress authenticates the
user and signs the request to FastAPI. FastAPI accepts only allowlisted sources
and normalized product identities. Unsupported URLs fail closed.

User can set:

- target raw price;
- target effective price after cashback;
- preferred region, if supported;
- alert preferences.

### 4.2 Cart/Favorites Synchronization

The planned production model supports automatic refresh of user cart/favorites
from Ozon, Wildberries, and Yandex Market.

Important boundary:

- user login happens only on the real marketplace page;
- Savello pages, backend, and workers never ask for marketplace passwords;
- client extracts only allowlisted session cookies/tokens needed for read-only
  cart/favorites synchronization;
- session bundle transfer requires explicit consent;
- backend stores the bundle only in encrypted form;
- sync worker decrypts only inside the controlled worker process and does not
  write raw tokens to logs, metrics, admin responses, or error payloads.

### 4.3 Admin-Managed Store Search

Admin can add stores/sources that participate in product search and comparison.
The product should not expand to arbitrary scraping. Every source must have:

- source code and display name;
- enabled/disabled status;
- allowed regions and delivery metadata policy;
- source difficulty/risk profile;
- fetch strategy and cost limits;
- compliance notes and ToS review status;
- parser/schema ownership and monitoring.

### 4.4 Price Comparison and Effective Price

Comparison results must include enough context to avoid misleading the user:

- raw price;
- availability;
- region;
- delivery cost or delivery uncertainty;
- delivery ETA when available;
- cashback status and estimated cashback amount;
- effective price = raw price + delivery - expected cashback;
- confidence that compared products are the same or acceptable analogs.

Low-confidence matches must be labeled as analogs or hidden until admin review.
The UI must not present uncertain matches as exact matches.

### 4.5 Personal Account

The planned personal account surface should show:

- tracked products;
- imported cart/favorites items;
- current price and price history;
- cashback/effective price;
- source and sync status;
- `reconnect_required` state for expired marketplace sessions;
- alert configuration;
- consent and disconnect controls.

### 4.6 Admin Area

The planned admin area should show:

- store/source registry;
- source health and quarantine;
- sync worker status;
- encrypted session bundle counts by state, without exposing bundle values;
- reconnect funnel metrics;
- price comparison quality;
- notification delivery and deduplication metrics;
- risk gate status for each marketplace/source.

### 4.7 Notifications

Notification triggers:

- target raw price reached;
- target effective price reached;
- price drop since last observation;
- new historical minimum;
- cheaper same product or cheaper acceptable analog found;
- session expired and user action required.

Notifications must be deduplicated, rate-limited, and preference-aware. They must
not include session data, private cart contents beyond the referenced item, or
unnecessary PII.

## 5. Production Model

### 5.1 Login and Session Capture

Planned flow:

1. User opens the Price Assistant connection flow from Savello Club.
2. WebView or extension opens the real Ozon/WB/YandexMarket login page.
3. User enters login/password only into the marketplace-controlled page.
4. Client waits until the marketplace session is established.
5. Client extracts only allowlisted session cookies/tokens for the selected
   marketplace and purpose.
6. Client displays a consent screen explaining what will be synchronized.
7. User explicitly consents to sending the session bundle to Savello backend.
8. Client sends the bundle to the planned WordPress/FastAPI connector endpoint.
9. Backend encrypts the bundle before persistence.
10. Sync worker uses the bundle to refresh cart/favorites.
11. `401`, `403`, `login_required`, `expired`, or equivalent signals set the
    connection state to `reconnect_required`.

Backend must never receive the marketplace password. If any client flow can see
or transmit password values, that implementation fails the security gate.

### 5.2 Session Bundle Content

Planned session bundle may contain only allowlisted values needed for the
specific source connector:

- source code, e.g. `ozon`, `wildberries`, `yandex_market`;
- user-owned connection id;
- capture timestamp;
- consent version;
- explicit scope, e.g. `cart_read`, `favorites_read`;
- allowlisted cookie/token names and values;
- optional marketplace region/session metadata required for read-only sync;
- client version and connector version.

Prohibited fields:

- marketplace password;
- Savello/WordPress auth cookies;
- browser password-manager data;
- full local storage dump;
- full session storage dump;
- raw page HTML containing private user data;
- payment data;
- passport, identity, or financial account data;
- non-allowlisted cookies/tokens.

### 5.3 Encryption and Access

Planned backend storage requirements:

- encrypt bundle values with authenticated encryption, preferably AES-256-GCM or
  an existing project-approved envelope encryption approach;
- store key ids/fingerprints separately from ciphertext;
- support key rotation without plaintext export;
- decrypt only in the sync worker or controlled service layer;
- redact bundle values in logs, admin APIs, metrics, traces, and exceptions;
- audit connect, consent, sync, reconnect, disconnect, and key-rotation events;
- fail closed when encryption config is missing or decryption fails.

### 5.4 Sync Worker

Planned worker responsibilities:

- select active connections that are due for sync;
- decrypt the session bundle in memory only;
- request cart/favorites pages or APIs within source policy;
- normalize imported items into product candidates;
- update cart/favorites snapshots and tracking records;
- emit price comparison/update events;
- detect expired sessions and set `reconnect_required`;
- back off on rate limits, blocks, captcha, and source instability;
- never attempt captcha bypass.

Worker operations must be idempotent by connection id, source, sync type,
marketplace item identity, and observation timestamp/window.

### 5.5 Reconnect State Machine

Planned states:

- `not_connected`: user has no active marketplace connection.
- `connecting`: client flow is in progress.
- `connected`: encrypted bundle exists and last sync is acceptable.
- `sync_failed_retryable`: temporary failure with retry/backoff.
- `source_limited`: source-level throttle, block, captcha, or quarantine.
- `reconnect_required`: user action required because session expired,
  forbidden, login required, or bundle cannot be used safely.
- `disconnected`: user or admin revoked connection and bundle is deleted or
  cryptographically destroyed.

`reconnect_required` is a planned user-action terminal state for the current
session. It is not implemented by this spec.

## 6. Planned Interfaces

All interfaces in this section are planned/not implemented. This spec does not
add, change, or remove public API behavior.

### 6.1 Connect Session Bundle

Planned endpoint shape:

```text
POST /wp-json/cashback/v1/price-assistant/connections
```

Authentication:

- logged-in Savello/WordPress user;
- nonce or equivalent CSRF protection;
- server-side proxy/signature to FastAPI if FastAPI persists the bundle.

Request shape:

```json
{
  "source": "ozon",
  "consent_version": "price-assistant-session-v1",
  "scope": ["cart_read", "favorites_read"],
  "captured_at": "2026-06-15T10:00:00Z",
  "connector_version": "0.1.0",
  "session_bundle": {
    "cookies": [
      {"name": "allowlisted_cookie_name", "value": "secret"}
    ],
    "tokens": [
      {"name": "allowlisted_token_name", "value": "secret"}
    ],
    "metadata": {
      "region": "default"
    }
  }
}
```

Validation requirements:

- reject unknown source;
- reject missing explicit consent;
- reject non-allowlisted cookie/token names;
- reject prohibited fields;
- reject oversized bundle;
- encrypt before persistence;
- return no secret values.

### 6.2 Disconnect Connection

Planned endpoint shape:

```text
DELETE /wp-json/cashback/v1/price-assistant/connections/{connection_id}
```

Behavior:

- user can disconnect only own connection;
- backend deletes ciphertext or renders it undecryptable;
- worker stops future syncs;
- audit event is written.

### 6.3 Sync Status

Planned response fields for personal account:

```json
{
  "connection_id": "conn_123",
  "source": "ozon",
  "status": "reconnect_required",
  "last_synced_at": "2026-06-15T10:00:00Z",
  "next_retry_at": null,
  "reason": "login_required"
}
```

No response may include cookies, tokens, or encrypted ciphertext.

## 7. Security and Privacy Requirements

### 7.1 Credential Boundary

- Marketplace password collection is prohibited.
- Backend password storage is prohibited.
- Backend receives only user-approved, allowlisted session cookies/tokens.
- WordPress/Savello auth cookies must never be included in marketplace session
  bundles.

### 7.2 Consent and Transparency

- Consent must be explicit, source-specific, and scope-specific.
- Consent text must explain that cart/favorites will be synchronized.
- User must be able to disconnect a marketplace connection.
- Consent version must be stored with the encrypted bundle metadata.

### 7.3 Data Minimization

- Store only the minimum session values required for read-only sync.
- Store only product/item fields needed for monitoring/comparison.
- Do not store full cart pages, full HTML snapshots, or non-product private data.
- Retention must be defined before production launch.

### 7.4 Fail-Closed Defaults

- Missing encryption config: do not accept bundle.
- Unknown source: reject.
- Non-allowlisted token/cookie: reject.
- Decryption failure: mark connection unusable and alert internally.
- `401/403/login_required/expired`: set `reconnect_required`.
- Captcha/block pressure: stop escalation and quarantine/limit source.

### 7.5 Logging and Observability

Logs, metrics, traces, and admin responses must not expose:

- cookies;
- tokens;
- passwords;
- HMAC secrets;
- encryption keys;
- proxy endpoint refs with credentials;
- payment details;
- raw private cart/favorites page content.

Safe metrics examples:

- count of active connections by source and state;
- count of sync attempts by source/result;
- reconnect-required rate;
- source block/captcha/rate-limit counts;
- notification sent/deduped counts.

## 8. Risk Matrix

| Risk | Severity | Likelihood | Product impact | Required mitigation | Gate |
| --- | --- | --- | --- | --- | --- |
| Marketplace ToS violation | High | Medium | Account blocks, legal/commercial risk, feature shutdown | Legal review per source; use official APIs where available; no password collection; no captcha bypass; source-specific go/no-go approval | Legal gate |
| Unstable marketplace API/DOM | High | High | Sync breaks, false prices, support load | Versioned connectors, fixtures, parser monitoring, source health, rollback/disable switch | Marketplace stability gate |
| Source blocks/rate limits | High | High | Lost sync, IP/proxy cost spikes, user distrust | Cost budgets, backoff, source quarantine, low sync frequency, no aggressive retries | Fetch risk gate |
| Cookie/token expiry | Medium | High | User must reconnect often | `reconnect_required` state, clear UX, expiry telemetry, reconnect funnel tracking | Consent UX gate |
| User security breach from session bundle leak | Critical | Low/Medium | Account takeover or private data exposure | Authenticated encryption, key rotation, strict redaction, least privilege, audit, access controls | Security gate |
| Overcollection of personal data | High | Medium | 152-ФЗ compliance risk, privacy harm | Data minimization, explicit consent, retention policy, DPIA/legal review, no full HTML dumps | 152-ФЗ gate |
| Cross-user access/IDOR | Critical | Low | One user sees another user's products or connection | WordPress auth boundary, `site_id + external_user_id` scoping, server-generated user identity, tests | Security gate |
| Misleading comparison | Medium | Medium | User buys wrong item or loses trust | Match confidence, analog labeling, admin review for uncertain matches | Product quality gate |
| Cashback estimate mismatch | Medium | Medium | Effective price is wrong | Snapshot timestamp, display policy, uncertainty labels, refresh before alert | Product quality gate |
| Notification spam | Medium | Medium | Unsubscribes, complaints, support load | Deduplication, rate limits, quiet hours/preferences, alert cooldowns | Notification gate |
| Worker idempotency bug | High | Medium | Duplicate items, duplicated alerts, inconsistent history | Idempotency keys for sync/import/alerts, unique constraints, retry tests | Worker gate |
| Secret exposure in admin/metrics | Critical | Low | Credential leak | Serialization tests, redaction helpers, safe labels only | Security gate |

## 9. 152-ФЗ and Privacy Notes

This document is not legal advice. Before production launch, counsel must review
the exact data categories, consent text, retention, cross-border processing,
processor/operator roles, user rights flow, and incident handling.

Minimum product requirements for 152-ФЗ posture:

- identify whether Savello acts as personal data operator for collected session
  metadata, cart/favorites product data, and notification data;
- define lawful basis and consent wording for marketplace sync;
- collect only data required for declared purposes;
- store consent version, timestamp, source, scope, and user identity;
- provide disconnect/delete flow for session bundle;
- define retention for imported cart/favorites snapshots;
- redact secrets and unnecessary PII from logs;
- document subprocessors and hosting/storage locations;
- prepare breach response procedure for session bundle exposure.

## 10. Roadmap

### Phase 0: Product + Risk Spec

Deliverable:

- this `spec.md`.

Acceptance:

- no code changes;
- no API changes;
- no tests added;
- risk matrix, roadmap, gates, and ADR backlog exist.

### Phase 1: Session Connector Design

Deliverables:

- detailed connector design for WebView/extension;
- cookie/token allowlist strategy per marketplace;
- consent UX copy and data inventory;
- legal/ToS review notes per marketplace.

Acceptance:

- password collection remains prohibited;
- allowlisted fields are source-specific;
- legal/security can approve or block each marketplace independently.

### Phase 2: Encrypted Bundle Storage

Deliverables:

- encrypted session bundle model;
- authenticated encryption and key rotation plan;
- connect/disconnect/status planned contracts implemented behind auth;
- audit and redaction tests.

Acceptance:

- bundle cannot be persisted without encryption config;
- no response/log/metric exposes bundle values;
- disconnect removes or cryptographically destroys bundle access.

### Phase 3: Sync Worker

Deliverables:

- idempotent cart/favorites sync worker;
- reconnect state machine;
- retry/backoff/quarantine behavior;
- static fixture tests for marketplace responses/pages.

Acceptance:

- `401/403/login_required/expired` sets `reconnect_required`;
- captcha/block pressure does not escalate into bypass;
- duplicate sync runs do not duplicate products or alerts.

### Phase 4: Marketplace Adapters

Deliverables:

- Ozon, Wildberries, and Yandex Market adapters;
- source-specific URL normalizers and extraction schemas;
- source health and parser drift monitoring.

Acceptance:

- each adapter has independent go/no-go status;
- tests use fixtures and fake network;
- admin can disable each source quickly.

### Phase 5: Comparison and Effective Price

Deliverables:

- admin-managed comparable stores;
- product matching/confidence model;
- effective price calculation using price, delivery, cashback, and availability;
- UI/API labels for exact match vs analog.

Acceptance:

- low-confidence matches are not shown as exact;
- cashback uncertainty is visible;
- comparison respects source and cost gates.

### Phase 6: Notifications and Admin Hardening

Deliverables:

- target price, price drop, new minimum, cheaper analog notifications;
- notification deduplication and rate limits;
- admin observability for sync, reconnect, source risk, and notification delivery.

Acceptance:

- no duplicate alert spam;
- user preferences are respected;
- admin can diagnose failures without seeing secrets.

## 11. Go/No-Go Gates

### Legal/ToS Gate

Go only if:

- legal review approves the source and planned access method;
- product has documented source-specific restrictions;
- no password collection or captcha bypass is required;
- user consent text is approved.

No-go if:

- source terms prohibit the planned access and no approved alternative exists;
- implementation needs password collection;
- implementation depends on bypassing access controls.

### Security Gate

Go only if:

- authenticated encryption is implemented and tested;
- key rotation/disable story exists;
- redaction tests cover logs/admin/metrics/errors;
- cross-user access tests pass;
- disconnect destroys access to bundle.

No-go if:

- bundles can be stored plaintext;
- secrets appear in logs or responses;
- user identity can be client-forged.

### Marketplace Stability Gate

Go only if:

- connector has fixtures and drift detection;
- source can be disabled independently;
- source health/quarantine signals are observable;
- parser failure does not corrupt product data.

No-go if:

- connector failure silently produces wrong prices;
- source cannot be quickly disabled.

### Cost and Fetch Risk Gate

Go only if:

- sync frequency is bounded;
- retries have backoff;
- source quarantine is active;
- expensive fetch strategies are explicitly gated.

No-go if:

- failures create aggressive retry loops;
- block/captcha signals increase fetch pressure.

### Consent UX Gate

Go only if:

- user sees what will be synchronized;
- consent is explicit and versioned;
- disconnect is available;
- `reconnect_required` is understandable and actionable.

No-go if:

- consent is bundled into unrelated terms;
- user cannot revoke connection.

### Observability Gate

Go only if:

- sync attempts, reconnect rate, source failures, and notification events are
  measurable without secrets;
- admin diagnostics can identify source-level failure;
- alerting exists for abnormal block/expiry/error spikes.

No-go if:

- production failures require inspecting raw tokens or private page content.

## 12. ADR Backlog

Required ADRs before implementation moves beyond design:

1. **Session Bundle Storage and Encryption**
   - Decide storage table/model, encryption envelope, key ids, rotation, deletion,
     and failure behavior.
2. **Allowlisted Token/Cookie Extraction**
   - Define source-specific allowlists, prohibited fields, client validation, and
     server validation.
3. **Reconnect State Machine**
   - Define connection states, transitions, terminal states, retry policy, and
     user-facing messages.
4. **Marketplace ToS and Access Posture**
   - Record per-source legal review, allowed methods, forbidden methods, and
     source-specific go/no-go status.
5. **152-ФЗ Data Minimization and Consent**
   - Define personal data categories, consent wording, retention, deletion, and
     audit requirements.
6. **Sync Worker Idempotency**
   - Define idempotency keys, duplicate handling, retry safety, and snapshot
     replacement/merge policy.
7. **Comparison and Effective Price Model**
   - Define same-product matching, analog matching, cashback uncertainty,
     delivery handling, and display labels.
8. **Notification Deduplication and Rate Limits**
   - Define event identity, cooldowns, user preferences, channel priority, and
     reconnect notifications.

## 13. Explicit Non-Goals for This Spec Task

This task intentionally does not implement:

- code changes;
- tests;
- migrations;
- WordPress REST API endpoints;
- FastAPI endpoints;
- browser extension or WebView;
- encrypted session bundle model;
- sync worker;
- marketplace adapters;
- real Ozon/WB/YandexMarket HTTP requests;
- product matching implementation;
- notifications;
- admin UI;
- ADR files;
- Obsidian session notes.

## 14. Source References

These references inform the risk posture. The implementation must re-check
source terms during the Legal/ToS gate because marketplace and legal documents
can change.

- Ozon rules: https://docs.ozon.ru/legal/terms-of-use/site/
- Wildberries user agreement: https://static-basket-03.wbbasket.ru/vol47/legalterms/ru/globalterms.html
- Yandex Market rules: https://yandex.ru/legal/market_termsofuse/ru/
- Federal Law No. 152-ФЗ "О персональных данных": https://pravo.gov.ru/proxy/ips/?docbody=&nd=102108261&page=all
