# Price Monitor Test Smoke

Date: 2026-06-30

## 2026-07-02 Joom Admin Settings And Live Provider Smoke

- GitHub Actions run: `28578507048`
- Run URL: `https://github.com/Igor-creato/monitor_cashback/actions/runs/28578507048`
- Deployed commit: `87c9aced2067b4e5e0ae3756d6004ea5eb9ea364`
- Jobs passed: `secret-scan`, `quality`, `deploy-test`
- Current release path:
  - `/home/igor/monitor_cashback/releases/87c9aced2067b4e5e0ae3756d6004ea5eb9ea364`
- Health after deploy:
  - `curl -fsS http://127.0.0.1:8000/health/live` -> `{"status":"ok"}`
  - `curl -fsS http://127.0.0.1:8000/health/ready` -> `{"status":"ok"}`
- Runtime compose status: `api`, `browserless`, `postgres`, `rabbitmq`, and
  `redis` are healthy; `worker` is running.

Covered checks:

- Backend admin settings now store the Joom provider URL, token, timeout, and
  wait selector. WordPress admin renders and saves the same settings through the
  existing backend settings form.
- Internal Browserless renderer is configured at
  `http://browserless:3000/chromium/content`; the token is stored separately in
  backend settings and sent as `Authorization: Bearer`.
- Browserless healthcheck is authorized with the container `TOKEN`; the first
  deploy attempts proved the required fixes:
  - `ghcr.io/browserless/chromium:2.26.1` -> manifest not found.
  - `/pressure` without token -> Browserless returned `401 Unauthorized`.
- `joom.ru` live pipeline smoke:
  - test URL: `https://www.joom.ru/ru/products/636f5d5db4165e01cef187e5`
  - watchlist add: created.
  - direct fetch: HTTP `200`, `product_data_not_found`.
  - browser fetch: provider request failed after waiting for
    `meta[property="product:price:amount"]`.
  - pipeline result: `fetch_failed`; no title or price extracted.
  - direct frontend API probe:
    `https://www.joom.ru/tokens/hydrate` returns
    `bot.proof_of_work_required`, so the server cannot obtain the anonymous API
    token without implementing Joom's bot-protection proof-of-work flow.
  - final source status restored to `disabled`.
- `citilink.ru` live pipeline smoke:
  - test URL:
    `https://www.citilink.ru/product/klyuch-aktivacii-movavika-maksimum-2026-dlya-mas-personalnaya-licenziy-2178432/`
  - watchlist add: created.
  - pipeline result: `ok`.
  - extracted title:
    `Ключ активации МОВАВИКА Максимум 2026 для Мас, персональная лицензия, годовая подписка [мм26мг]`
  - extracted price: `661000` RUB minor units.
  - cleanup: test watchlist item deleted.
- `aliexpress.ru` smoke:
  - source status remains `disabled`.
  - watchlist add returns `unsupported_store`.
  - direct fetch of `https://aliexpress.ru/item/1005010654381286.html`
    returns HTTP `200`, `1889` bytes, and is classified as
    `captcha_detected`.

Notes:

- Joom support is wired through admin settings and a dedicated source-aware
  browser/provider adapter. The current self-hosted Browserless path does not
  make Joom monitorable from the test server because Joom requires a
  bot-protection proof-of-work step before issuing the anonymous frontend API
  token.
- Do not enable custom proof-of-work, CAPTCHA, fingerprint, or anti-bot bypass
  logic in this code path. To make Joom production-ready, select an approved
  data-provider/API contract or get explicit permission for a compliant Joom
  API integration.

## 2026-07-02 Joom Browser Provider Adapter

- GitHub Actions run: `28575449938`
- Run URL: `https://github.com/Igor-creato/monitor_cashback/actions/runs/28575449938`
- Deployed commit: `bae5519a3f1d9fdb718e4ecca449d8407f54f46f`
- Jobs passed: `secret-scan`, `quality`, `deploy-test`
- Health after deploy:
  - `curl -fsS http://127.0.0.1:8000/health/live` -> `{"status":"ok"}`
  - `curl -fsS http://127.0.0.1:8000/health/ready` -> `{"status":"ok"}`
- Current release path:
  - `/home/igor/monitor_cashback/releases/bae5519a3f1d9fdb718e4ecca449d8407f54f46f`

Covered checks:

- `joom.ru` source remains `disabled` on the test server because
  `PRICE_MONITOR_JOOM_BROWSER_PROVIDER_URL` is not configured.
- `joom.ru` direct server fetch still returns only the small SPA shell:
  HTTP `200`, `7434` bytes, no extracted price.
- `aliexpress.ru` remains `disabled`; direct fetch is classified as
  `captcha_detected`.
- `citilink.ru` remains `active`; direct fetch extracted price `612000` RUB minor
  units.
- Citilink watchlist smoke created a test item, ran `FetchPipeline`, returned
  `pipeline_status=ok`, returned price chart HTTP `200` with latest price
  `612000`, and deleted the test item.
- Active test watchlist items with prefix `joom-adapter-%`: `0`.

Notes:

- Joom support in this commit is a source-aware browser/provider adapter and
  OpenGraph metadata extraction fallback. Enabling Joom on the server requires
  configuring an approved rendered HTML provider URL/token first.
- AliExpress live integration was not added. Provider/API options are recorded
  in `docs/aliexpress-provider-options.md`.

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
