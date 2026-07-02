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

## Marketplace Fetching Policy

The service may use source-specific public product-page fetching strategies,
including managed unblocker APIs, browser rendering, proxy rotation, and
challenge-aware adapters, when those strategies are configured for an approved
monitored source. These fetchers must still preserve the security boundaries in
this document: SSRF checks before network access, secret redaction, source-level
rate limits, retry budgets, and auditable status reporting.

The service must not store marketplace login/passwords, unapproved raw cookies,
or raw browser session captures, and it must not log secrets, proxy credentials,
provider tokens, or challenge tokens. Cart and favorites monitoring requires
official OAuth, partner API access, explicit user consent, or another approved
legal and secure design.

## Secrets

`.env.example` contains only synthetic placeholders. Production secrets must be
provided by deployment secret storage and never committed.
