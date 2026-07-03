# Architecture

## Service Shape

The repository is now a neutral Python/FastAPI service shell. It keeps the
runtime and deployment infrastructure that is reusable for future search or
comparison work:

- `core`: runtime settings, logging, and HMAC signing helpers.
- `db`: SQLAlchemy base/session wiring for future tables.
- `workers`: Celery app configured against RabbitMQ and Redis.
- `migrations`: Alembic wiring plus a cleanup migration for the removed
  price-monitor domain schema.

## Current HTTP Surface

- `GET /health/live`
- `GET /health/ready`

No product-link monitoring, watchlist, source, fetch, price-history, or alert API
is active.

## Future Extension Point

Future product search/comparison work should add new domain modules and API
routes behind the existing service shell. Keep request signing, secret handling,
database migrations, and worker queues reusable and source-neutral.
