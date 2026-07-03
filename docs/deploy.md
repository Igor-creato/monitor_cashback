# Deploy

## Local/Test Stage

The supported deployment target remains Docker Compose:

```powershell
rtk docker compose up -d --build
rtk docker compose ps
rtk docker compose logs api
```

Run migrations before accepting traffic:

```powershell
rtk docker compose run --rm api alembic upgrade head
```

The current migration head drops old product-link monitoring domain tables and
leaves the database ready for future service work.

## GitHub Actions Test Deployment

The `CI` workflow runs quality gates and secret scanning on pull requests and
pushes. It deploys to the test server only after a successful `push` to
`develop`.

The workflow uses:

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
```

`PRICE_MONITOR_BIND_ADDRESS=127.0.0.1` keeps the API and backing services bound
to localhost on the test server unless a reviewed proxy/public exposure change
sets a different value.

## Smoke Checks

```powershell
rtk curl http://localhost:8000/health/live
rtk curl http://localhost:8000/health/ready
```

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
