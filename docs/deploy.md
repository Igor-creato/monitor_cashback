# Deploy

## Local/Test Stage

The supported foundation deployment target is Docker Compose:

```powershell
rtk docker compose up -d --build
rtk docker compose ps
rtk docker compose logs api
```

Run migrations before accepting traffic:

```powershell
rtk docker compose run --rm api alembic upgrade head
```

## PostgreSQL Major Upgrades

The test deployment workflow upgrades PostgreSQL major versions without
rewriting the legacy data volume in place. Before switching to the target
PostgreSQL image, it stops API/worker writers, dumps the current database with
`pg_dump`, starts the target major on `postgres-data-pg18`, restores with
`pg_restore`, and then runs Alembic plus health checks. The legacy
`postgres-data` volume is intentionally retained as the rollback data source for
the previous release.

PostgreSQL 18+ uses `/var/lib/postgresql/18/docker` as `PGDATA`, so the Compose
volume is mounted at `/var/lib/postgresql` instead of the pre-18
`/var/lib/postgresql/data` path.

## GitHub Actions Test Deployment

The `CI` workflow runs quality gates and secret scanning on pull requests and
pushes. It deploys to the test server only after a successful `push` to
`develop`.

The `master` branch is intentionally not connected to test deployment. It is
reserved for a later production deployment workflow.

Configure a GitHub Environment named `test` with these values:

- Environment variables: `TEST_SERVER_HOST`, `TEST_SERVER_USER`,
  `TEST_SERVER_PORT` (optional, defaults to `22`).
- Environment secrets: `TEST_SERVER_SSH_KEY`, `TEST_SERVER_KNOWN_HOSTS`.

Configure `GITLEAKS_LICENSE` as an optional repository or organization secret
only when required for the repository owner type. It is used by the pre-deploy
secret scan, not by the test deployment environment.

The SSH user must be able to run Docker Compose v2. The workflow creates the
base deployment folders when needed:

```text
/home/igor/monitor_cashback/releases/<git-sha>
/home/igor/monitor_cashback/current
/home/igor/monitor_cashback/shared/.env
```

The workflow intentionally does not create `shared/.env`. Put real runtime
values on the server before the first deploy, and keep them out of Git:

```bash
COMPOSE_PROJECT_NAME=monitor_cashback
PRICE_MONITOR_BIND_ADDRESS=127.0.0.1
PRICE_MONITOR_ENVIRONMENT=test
PRICE_MONITOR_EXTERNAL_BASE_URL=http://127.0.0.1:8000
POSTGRES_DB=price_monitor
POSTGRES_USER=price_monitor
POSTGRES_PASSWORD=<server-managed-postgres-password>
RABBITMQ_DEFAULT_USER=price_monitor
RABBITMQ_DEFAULT_PASS=<server-managed-rabbitmq-password>
PRICE_MONITOR_DATABASE_URL=postgresql+psycopg://price_monitor:<server-managed-postgres-password>@postgres:5432/price_monitor
PRICE_MONITOR_REDIS_URL=redis://redis:6379/0
PRICE_MONITOR_RABBITMQ_URL=amqp://price_monitor:<server-managed-rabbitmq-password>@rabbitmq:5672//
PRICE_MONITOR_HMAC_SECRETS=<server-managed-secret>
PRICE_MONITOR_HMAC_REPLAY_WINDOW_SECONDS=300
PRICE_MONITOR_DB_POOL_RECYCLE_SECONDS=3600
PRICE_MONITOR_BROWSERLESS_TOKEN=<server-managed-browserless-token>
PRICE_MONITOR_DECODO_WEB_SCRAPING_API_URL=https://scraper-api.decodo.com/v2/scrape
PRICE_MONITOR_DECODO_WEB_SCRAPING_API_TOKEN=<server-managed-decodo-web-scraping-api-token>
PRICE_MONITOR_DECODO_WEB_SCRAPING_TIMEOUT_SECONDS=25
PRICE_MONITOR_DECODO_WEB_SCRAPING_PROXY_POOL=premium
PRICE_MONITOR_DECODO_WEB_SCRAPING_HEADLESS=html
PRICE_MONITOR_DECODO_WEB_SCRAPING_GEO=
```

`PRICE_MONITOR_BIND_ADDRESS=127.0.0.1` keeps the API and backing services bound
to localhost on the test server unless a reviewed proxy/public exposure change
sets a different value.

`PRICE_MONITOR_BROWSERLESS_TOKEN` protects the internal Browserless renderer
used by source-specific browser fallback such as `joom.ru`. The renderer is not
published to a host port; the worker reaches it over the private compose
network.

`PRICE_MONITOR_DECODO_WEB_SCRAPING_API_TOKEN` enables the managed unblocker
fallback for protected public product pages. Keep it only in the server-managed
environment file; do not store it in admin settings, database rows, logs, docs,
or Git.

The deployment job fails closed if SSH settings are missing or
`/home/igor/monitor_cashback/shared/.env` does not exist.

## Smoke Checks

```powershell
rtk curl http://localhost:8000/health/live
rtk curl http://localhost:8000/health/ready
```

GitHub Actions runs the same health checks on the test server after migrations
and `docker compose up -d --build`.

## Rollback

For test-stage rollback, relink `current` to the previous release and restart
the application with the server-managed environment file:

```bash
BASE_DIR=/home/igor/monitor_cashback
PREVIOUS_SHA=<previous-release-sha>
ln -sfn "$BASE_DIR/releases/$PREVIOUS_SHA" "$BASE_DIR/current"
cd "$BASE_DIR/current"
PRICE_MONITOR_ENV_FILE="$BASE_DIR/shared/.env" docker compose --env-file "$BASE_DIR/shared/.env" up -d --build
curl -fsS http://127.0.0.1:8000/health/ready
```

Database migrations must be forward-compatible unless a separate rollback plan
has been reviewed.
