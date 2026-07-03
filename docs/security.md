# Security

## Current Boundary

The service shell exposes only health endpoints and does not perform marketplace
fetching, browser rendering, managed unblocker calls, or product URL ingestion.

## Request Authentication

HMAC helper code remains available for future WordPress-to-service endpoints.
When new mutating endpoints are added, they should bind the HTTP method, path,
timestamp, request id, and exact body hash to the signature.

## Secrets

`.env.example` contains only synthetic placeholders. Production secrets must be
provided by deployment secret storage and never committed.
