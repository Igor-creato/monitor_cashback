# Security

## Request Authentication

The service trusts only requests signed by the WordPress proxy. HMAC validation
binds the HTTP method, path, timestamp, request id, and exact body hash. Mutating
requests require idempotency keys to make retries safe.

## URL Safety

Product URL monitoring is fail-closed:

- only `http` and `https` schemes are accepted;
- local hostnames, private IP literals, loopback, link-local, multicast,
  reserved, and unspecified addresses are rejected;
- tracking query parameters such as `utm_*`, `fbclid`, `gclid`, and `yclid` are
  removed before hashing;
- future network fetchers must re-check redirects before making each request.

## Marketplace Policy

The service must not store marketplace login/passwords, raw cookies, browser
session captures, captcha bypass logic, fingerprint bypass logic, or proxy
evasion logic. Cart and favorites monitoring requires official OAuth, partner
API access, or another approved legal and secure design.

## Secrets

`.env.example` contains only synthetic placeholders. Production secrets must be
provided by deployment secret storage and never committed.
