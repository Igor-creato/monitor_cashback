# API Contract

## Authentication

Mutating WordPress-facing requests must include:

- `X-Request-Id`: stable request identifier for logs and outbox events.
- `X-Request-Timestamp`: Unix seconds, accepted only inside the replay window.
- `X-Body-SHA256`: SHA-256 hex digest of the exact request body.
- `X-Signature`: HMAC-SHA256 over method, path, timestamp, request id, and body
  hash.
- `Idempotency-Key`: required for mutating endpoints.

Error bodies use:

```json
{
  "error": {
    "code": "authentication_failed",
    "message": "missing authentication headers",
    "request_id": "req-123"
  }
}
```

## Initial Endpoints

- `GET /health/live`
- `GET /health/ready`
- `POST /api/v1/watchlist/items`
- `GET /api/v1/watchlist/items`
- `DELETE /api/v1/watchlist/items/{item_id}`
- `GET /api/v1/products/{product_id}/price-history`
- `GET /api/v1/sources/status`

`POST /api/v1/watchlist/items` accepts:

```json
{
  "user_id": "wp-user-1",
  "url": "https://example.com/product?id=42",
  "target_price_minor": 12345,
  "currency": "RUB"
}
```

The endpoint returns `201` for a new item and `200` for a duplicate canonical
URL already tracked by the same user.
