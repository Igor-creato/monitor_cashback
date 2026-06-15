# Price Monitor

Minimal FastAPI backend skeleton for the price-monitor service.

## Local checks

```powershell
Set-Location backend
python -m pytest -q
python -m ruff check .
python -m ruff format .
```

## Run

```powershell
Set-Location backend
uvicorn app.main:app --reload
```

Health endpoint:

```text
GET /health
```

## Local MinIO object storage

Local development uses MinIO as an S3-compatible object storage for product
images. The default bucket is `product-images`.

Start only object storage:

```powershell
rtk docker compose up -d minio minio-init
```

Or start the full local stack:

```powershell
rtk docker compose up -d
```

MinIO endpoints:

- API: `http://localhost:9000`
- Console: `http://localhost:9001`
- Bucket: `product-images`

The backend talks to MinIO through `OBJECT_STORAGE_ENDPOINT=http://minio:9000`
inside Docker Compose. For production, replace the `OBJECT_STORAGE_*`
environment variables with credentials, endpoint, bucket, and public base URL
for any S3-compatible storage/CDN.

## Frontend contract

- [Price chart contract](docs/frontend-price-chart-spec.md)

## Marketplace session storage

Marketplace session bundles are accepted only through the HMAC-protected
`/v1/marketplace-connections` endpoints, after source-specific allowlist rows
exist in the database. The service rejects bundle persistence when encryption is
not configured.

Required encryption settings:

```text
MARKETPLACE_SESSION_KEYRING=v1:<base64-encoded-32-byte-key>[,v2:<base64-encoded-32-byte-key>]
MARKETPLACE_SESSION_ACTIVE_KEY_VERSION=v2
```

`MARKETPLACE_SESSION_ACTIVE_KEY_VERSION` is the primary key for new writes.
Other configured key versions remain previous keys for decrypting existing
secrets. Session secret rows store `payload_format_version`: legacy direct
service-layer payloads use version `1`, while API-captured marketplace bundles
use version `2` with `format_version`, `marketplace`, allowlisted cookies,
allowlisted tokens, `captured_at`, and optional `user_agent_hint`/`region_hint`.

Non-allowlisted cookie/token names are dropped before encryption. A bundle that
contains no allowlisted values after filtering is rejected fail-closed.

Do not put marketplace passwords in requests or logs. Admin diagnostics expose
connection status and `key_version` only, never cookies, tokens, ciphertext, or
wrapped DEKs.

## Demo seed data

Development-only demo seed data creates two local GPU products, subscriptions
for `wp:savelloclub.ru:demo`, cashback snapshots, and 30 days of price history
for checking product cards and the price chart.

The local database must already exist and be migrated. The seed script does not
create tables and refuses to run unless `APP_ENV=development`.

Docker:

```powershell
rtk docker compose exec -e APP_ENV=development backend-api python -m app.dev.seed_demo_data
```

Local backend:

```powershell
Set-Location backend
$env:APP_ENV = "development"
$env:DATABASE_URL = "mysql+pymysql://cashback:cashback@localhost:3306/cashback"
rtk python -m app.dev.seed_demo_data
```
