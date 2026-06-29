# Price Monitor Service

Backend microservice foundation for product price monitoring. The service is
separate from the `cash-back` WordPress plugin and owns product URL intake,
watchlist state, product records, price history, source health, scheduling, and
worker orchestration.

## What v1 Provides

- FastAPI application with live/readiness health endpoints.
- WordPress-facing watchlist API protected by HMAC request signatures and
  idempotency keys.
- PostgreSQL-owned domain tables for products, watchlist items, price points,
  source status, idempotency records, outbox events, inbox messages, and fetch
  jobs.
- RabbitMQ/Celery worker foundation with late acknowledgements, low prefetch,
  durable publish settings, and retry backoff.
- Transactional outbox and inbox primitives for at-least-once delivery with
  duplicate-safe consumers.
- Interfaces for future modules: product search/comparison, official
  marketplace OAuth, cart import, and favorites import.

## Local Quick Start

```powershell
rtk python -m pip install -e ".[dev]"
rtk python -m pytest
rtk docker compose up -d --build
```

API docs are available at `http://localhost:8000/docs` when the compose stack is
running.

## Boundaries

The WordPress plugin owns UI, account flows, proxy signing, and cashback UX. The
service does not store marketplace passwords, raw cookies, browser session
captures, or captcha-bypass logic. Cart and favorites monitoring can only be
added through official OAuth/partner access or another approved legal and secure
integration.
