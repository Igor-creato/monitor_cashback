# Price Monitor Test Smoke

Date: 2026-06-30

## Backend Deploy

- GitHub Actions run: `28466837579`
- Run URL: `https://github.com/Igor-creato/monitor_cashback/actions/runs/28466837579`
- Deployed commit: `646a840f20e20e5a42a7bb5000efa47021c9fa78`
- Jobs passed: `quality`, `secret-scan`, `deploy-test`
- Health after deploy:
  - `curl -fsS http://127.0.0.1:8000/health/live` -> `{"status":"ok"}`
  - `curl -fsS http://127.0.0.1:8000/health/ready` -> `{"status":"ok"}`
- Runtime versions from deploy log:
  - Python `3.14.6`
  - FastAPI `0.138.2`
  - PostgreSQL `18.4`
  - Redis `8.8.0`
  - RabbitMQ `4.3.2`

## Migration Follow-Up

The first signed API smoke found that the test database was still at
`20260629_0001`, while the deployed code required `20260630_0002`.

Root cause: the deploy workflow ran `docker compose run --rm api alembic upgrade head`
before `docker compose up --build`, so Alembic executed from the previous API image.

Fix added: `.github/workflows/ci.yml` now runs the migration with `--build`, guarded by
`tests/ops/test_ci_deploy_workflow.py`.

Server recovery command used on the test host:

```bash
cd /home/igor/monitor_cashback/current
PRICE_MONITOR_ENV_FILE=/home/igor/monitor_cashback/shared/.env \
  docker compose --env-file /home/igor/monitor_cashback/shared/.env \
  run --rm --build api alembic upgrade head
```

Observed result:

```text
Running upgrade 20260629_0001 -> 20260630_0002, price monitor vertical slice
20260630_0002 (head)
```

## Signed Server Smoke

Helper used: `tools/price_monitor_server_smoke.py`

Invocation shape:

```powershell
Get-Content -Raw tools/price_monitor_server_smoke.py |
  ssh -i "$env:USERPROFILE/.ssh/service" -p 56789 igor@5.35.124.64 `
    "cd /home/igor/monitor_cashback/current && docker compose --env-file /home/igor/monitor_cashback/shared/.env exec -T api python -"
```

Run id: `task10-a06c3f10b103`

Covered checks:

- added supported source `example.com`
- unsupported source returned `unsupported_store`
- supported URL created a watchlist item
- duplicate URL returned `duplicate_watchlist_item`
- user limit returned `limit_exceeded`
- controlled fetch pipeline hydrated product card fields
- price chart returned `1` point
- target price created alert event `1c1ff582-9034-4286-a7ef-c1d6adeabea5`
- notification outbox event created `ebaebf74-4f21-47e0-a4aa-cdc7e78360b9`
- delete marked watchlist item `11ec6787-16a7-42db-8414-1d96fefc141c` as `deleted`
- product and price history remained after delete

Smoke output:

```json
{"alert_event_id":"1c1ff582-9034-4286-a7ef-c1d6adeabea5","chart_points":1,"delete_status":"deleted","fetch_attempt_id":"500d3990-88f2-4d9c-b1d9-b5aa3fd71739","fetch_status":"ok","limit_checked_at":10,"outbox_event_id":"ebaebf74-4f21-47e0-a4aa-cdc7e78360b9","price_point_id":"e2bdd618-3b6b-42ac-a9ba-72eb57efca42","product_id":"ac2b9d10-3e02-4143-a0dd-d3b99b5409e4","result":"passed","run_id":"task10-a06c3f10b103","settings_restored":"not_needed","source":"example.com","watchlist_item_id":"11ec6787-16a7-42db-8414-1d96fefc141c"}
```

## WordPress Dispatch Evidence

WordPress branch: `feature/price-monitor-wordpress-ui`

Command:

```powershell
cd F:\wamp64\www\kash-back\wp-content\plugins\cash-back\development\test
php vendor/bin/phpunit --configuration phpunit.xml.dist tests/PriceMonitorAlertDispatchTest.php
```

Result:

```text
OK (23 tests, 76 assertions)
```

The covered happy path asserts that the internal REST callback returns
`array( 'status' => 'sent' )` and records one `wp_mail()` call.
