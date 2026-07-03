# Monitor Cashback Service Shell

Reusable backend infrastructure for future cashback-adjacent services.

The product-link price monitoring implementation has been removed. The repo now
keeps only the deployable service shell that can later host a product search,
comparison, or another approved backend workflow.

## What Remains

- FastAPI application with `/health/live` and `/health/ready`.
- PostgreSQL, Redis, RabbitMQ, Celery, Alembic, Docker Compose, and GitHub
  Actions deployment wiring.
- HMAC request-signing helpers for a future WordPress-to-service API.
- A migration path that drops the old price-monitor domain tables on upgrade.

## Local Quick Start

```powershell
rtk python -m pip install -e ".[dev]"
rtk python -m pytest
rtk docker compose up -d --build
```

API docs are available at `http://localhost:8000/docs` when the compose stack is
running.

## Boundaries

No marketplace product fetching, source adapters, Decodo/Browserless integration,
watchlist API, price history API, or alert dispatch code remains in this shell.
New search/comparison behavior should be designed and implemented as a separate
feature on top of this infrastructure.
