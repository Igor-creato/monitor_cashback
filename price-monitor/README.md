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
