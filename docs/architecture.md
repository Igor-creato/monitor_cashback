# Architecture

## Service Shape

`price-monitor` is a Python/FastAPI service with PostgreSQL as the system of
record, RabbitMQ as the durable broker, Celery workers for asynchronous work,
and Redis for cache, locks, rate-limit state, and Celery result metadata.

The first foundation keeps modules small:

- `api/v1`: HTTP contracts exposed to the WordPress proxy.
- `core`: config, HMAC signing, URL safety policy, idempotency.
- `db`: SQLAlchemy base and session wiring.
- `domains`: service-owned business boundaries.
- `adapters`: broker, HTTP, and storage integrations.
- `workers`: Celery app and task entrypoints.
- `observability`: health and metric helpers.

## Data Flow

1. WordPress proxy sends a signed request with `X-Request-Id`,
   `X-Request-Timestamp`, `X-Body-SHA256`, `X-Signature`, and, for mutations,
   `Idempotency-Key`.
2. API verifies the HMAC signature and reserves the idempotency key.
3. The domain service normalizes and validates the product URL with a
   fail-closed SSRF policy.
4. The same database transaction writes the product/watchlist change and an
   outbox event.
5. An outbox dispatcher publishes pending events to RabbitMQ with persistent
   delivery.
6. Workers record inbox messages before processing so retries and redeliveries
   are duplicate-safe.

## Future Extension Points

- `ProductSourceAdapter.fetch_product`: source-specific public product fetch.
- `ProductNormalizer.normalize_url`: canonical URL and identity rules.
- `ProductMatcher.match_offer`: product search/comparison matching.
- `MarketplaceOAuthProvider`: official marketplace authorization flows.

Source-specific public product-page monitoring may use managed unblocker APIs,
browser rendering, proxy rotation, and challenge-aware adapters behind
`ProductSourceAdapter.fetch_product`. Cart and favorites imports must plug into
official OAuth, partner APIs, explicit user consent, or another approved secure
integration; marketplace passwords, unapproved raw cookies, and raw browser
session captures remain out of scope.
