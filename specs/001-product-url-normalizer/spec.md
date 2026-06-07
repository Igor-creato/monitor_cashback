# Feature Specification: Product URL Normalizer

**Feature Branch**: `001-product-url-normalizer`

**Created**: 2026-06-07

**Status**: Draft

**Input**: User description: "Реализовать URL normalizer для дедупликации товаров. Результат нормализации: source, external_product_id, canonical_url, region_code, variant_hash. Поддержать только тестовые источники: testshop.local, example-market.local, demo-store.local. TDD: UTM удаляются; ref удаляется; product id извлекается; region извлекается; variant_hash создаётся только при наличии variant; неизвестный домен даёт UnsupportedSourceError; сетевых запросов нет. Scope lock: не добавляй реальные маркетплейсы; не делай scraping; не делай кэшбэк resolve; не создавай endpoints."

## Clarifications

### Session 2026-06-07

- Q: What should `region_code` be when a supported URL does not include `region`? → A: `region_code=default`

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deduplicate Supported Product URLs (Priority: P1)

As a maintainer of the product monitoring service, I need product URLs from supported test sources to normalize into a stable product identity so duplicate tracking records can be detected reliably.

**Why this priority**: Stable product identity is the core value of the feature; without it, the service cannot safely deduplicate product monitoring inputs.

**Independent Test**: Can be fully tested by submitting supported test-source URLs with tracking parameters and confirming the normalized result contains the expected source, product id, canonical URL, region, and variant identity.

**Acceptance Scenarios**:

1. **Given** `https://testshop.local/product/123?utm_source=x`, **When** the URL is normalized, **Then** the result has `source=testshop`, `external_product_id=123`, and `canonical_url=https://testshop.local/product/123`.
2. **Given** `https://example-market.local/item/abc-777?ref=partner&utm_campaign=1&region=msk`, **When** the URL is normalized, **Then** the result has `source=example_market`, `external_product_id=abc-777`, `region_code=msk`, and a canonical URL without `ref` or UTM parameters.

---

### User Story 2 - Preserve Region and Variant Deduplication Inputs (Priority: P2)

As a maintainer, I need region and variant information to be represented predictably so products that differ by region or explicit variant are not accidentally merged.

**Why this priority**: Region and variant are part of the intended deduplication result and affect whether two normalized URLs represent the same tracked product.

**Independent Test**: Can be tested by normalizing URLs with and without `region` and `variant` values and checking that region is extracted and variant identity appears only when an explicit variant is present.

**Acceptance Scenarios**:

1. **Given** a supported URL with `region=msk`, **When** the URL is normalized, **Then** the result includes `region_code=msk`.
2. **Given** a supported URL with `variant=<value>`, **When** the URL is normalized, **Then** the result includes a non-empty `variant_hash`.
3. **Given** a supported URL without `variant`, **When** the URL is normalized, **Then** the result does not include a variant hash value.

---

### User Story 3 - Reject Unsupported Sources Without External Access (Priority: P3)

As a maintainer, I need unsupported domains to be rejected without any outbound lookup so tests remain deterministic and the service does not accidentally reach real marketplaces.

**Why this priority**: This protects scope boundaries and prevents accidental network behavior while still allowing clear failure handling.

**Independent Test**: Can be tested by normalizing an unknown-domain URL while network access is guarded and confirming rejection occurs without any network request.

**Acceptance Scenarios**:

1. **Given** a URL from an unknown domain, **When** the URL is normalized, **Then** normalization fails with `UnsupportedSourceError`.
2. **Given** any normalization test case, **When** the URL is normalized, **Then** no network request is made.

### Edge Cases

- URLs containing UTM parameters must normalize to the same canonical URL as equivalent URLs without those parameters.
- URLs containing `ref` must normalize to the same canonical URL as equivalent URLs without `ref`.
- URLs from unknown domains must fail closed instead of returning a partial or guessed product identity.
- URLs without an explicit `variant` must not create a variant hash.
- URLs with an explicit `variant` must create a deterministic variant identity suitable for deduplication.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST normalize supported product URLs into a result containing `source`, `external_product_id`, `canonical_url`, `region_code`, and `variant_hash`.
- **FR-002**: System MUST support only these sources: `testshop.local`, `example-market.local`, and `demo-store.local`.
- **FR-003**: System MUST map `testshop.local` to `source=testshop`.
- **FR-004**: System MUST map `example-market.local` to `source=example_market`.
- **FR-005**: System MUST remove all UTM parameters from the canonical URL.
- **FR-006**: System MUST remove `ref` from the canonical URL.
- **FR-007**: System MUST extract the external product id from the supported source URL pattern.
- **FR-008**: System MUST extract `region` into `region_code` when the URL includes a region value.
- **FR-009**: System MUST set `region_code=default` when a supported URL does not include a region value.
- **FR-010**: System MUST create `variant_hash` only when the URL includes an explicit `variant` value.
- **FR-011**: System MUST reject unknown domains with `UnsupportedSourceError`.
- **FR-012**: System MUST complete normalization without outbound network requests.
- **FR-013**: System MUST NOT add real marketplace support, scraping, cashback resolving, WordPress API behavior, browser extension behavior, or endpoint behavior as part of this feature.

### Scope Boundaries *(mandatory)*

- **In Scope**: URL normalization for the three supported test domains; extraction of product id, region, and variant identity; canonical URL generation with tracking parameters removed; deterministic rejection of unsupported domains; tests proving no network access.
- **Out of Scope**: Real marketplace integrations, scraping, cashback resolve, WordPress REST API development, browser extension development, public endpoints, database changes, queue contracts, migrations, and server changes.

### Security and Abuse Considerations *(mandatory)*

- The feature is an internal normalization capability and is not externally reachable by itself.
- Input URLs must be parsed and normalized deterministically; unsupported domains must fail closed.
- No public endpoint, rate limiting behavior, or authentication behavior is introduced by this feature.
- The feature must not log or expose sensitive data; URL query parameters used only for tracking or referral must not be preserved in canonical output.

### Idempotency and Retry Behavior *(mandatory if API, worker, queue, external integration, money, balance, CPA, or payout behavior is involved)*

- Deduplication identity is represented by the normalized result fields, especially `source`, `external_product_id`, `region_code`, and `variant_hash`.
- No retry, backoff, terminal status, or DLQ behavior is introduced because this feature performs no external calls and creates no queue or worker behavior.
- No money, balance, CPA transaction, payout, or ledger behavior is introduced or modified.

### Documentation Impact *(mandatory)*

- **Obsidian notes to update**: None for specification creation. Implementation may update `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian\knowledge\integrations\monitor-cashback.md` only if the normalizer becomes documented service behavior.

### Key Entities *(include if feature involves data)*

- **Normalized Product URL Result**: Represents the stable deduplication output for a product URL; includes source, external product id, canonical URL, region code, and optional variant hash.
- **Supported Test Source**: Represents one of the explicitly allowed test domains and its source identifier.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of specified supported-domain examples normalize to the expected source, product id, and canonical URL.
- **SC-002**: 100% of URLs containing UTM or `ref` tracking parameters produce canonical URLs without those parameters.
- **SC-003**: 100% of URLs with `region` preserve the region value in the normalized result.
- **SC-004**: 100% of URLs without `variant` produce no variant hash, and 100% of URLs with `variant` produce a deterministic variant hash.
- **SC-005**: 100% of unknown-domain normalization attempts fail with `UnsupportedSourceError`.
- **SC-006**: 100% of normalization tests complete without outbound network requests.

## Assumptions

- The supported test sources use stable path patterns sufficient to extract product ids for the examples and tests in this feature.
- If a URL has no region value, the normalized result uses `region_code=default`.
- `variant_hash` represents a deterministic identity for an explicit variant value; the exact hashing method is an implementation detail and is not part of the public contract.
- This feature is a pure local normalization capability and does not persist data by itself.
