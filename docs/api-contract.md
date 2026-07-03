# API Contract

## Current Endpoints

- `GET /health/live`
- `GET /health/ready`

`/health/live` verifies that the API process is running. `/health/ready` also
checks database connectivity with `SELECT 1`.

## Signing Helper

The package still provides HMAC helper functions for future service routes:

- `build_signed_headers(...)`
- `verify_signed_request(...)`

No signed business endpoints are currently exposed.
