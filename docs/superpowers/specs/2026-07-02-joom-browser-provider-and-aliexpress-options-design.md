# Joom Browser Provider And AliExpress Options Design

Date: 2026-07-02
Status: Approved for implementation

## Goal

Make `joom.ru` monitorable through a dedicated browser/provider path with an
approved managed unblocker, browser-plus-proxy provider, or source-specific
adapter, and document the AliExpress data acquisition options before any paid
or credentialed integration is selected.

## Context

`citilink.ru` works through direct HTTP and JSON-LD extraction. `joom.ru` behaves differently by runtime location: local HTTP can receive SSR/OpenGraph product metadata, while the test server receives only a small SPA shell with `api.joom.ru` hints and no price. `aliexpress.ru` currently returns a CAPTCHA/punish page and needs either an official/partner API or an approved managed fetching strategy with budgeting, rate limits, diagnostics, and secret redaction.

## Joom Design

The backend keeps `FetchPipeline` as the shared orchestration layer. Joom support is added as source-specific acquisition:

- Direct HTTP still runs first.
- Product metadata extraction accepts JSON-LD and OpenGraph product meta tags.
- If direct HTTP cannot produce product data and the `joom.ru` source has `browser_fallback_allowed=true`, the pipeline can call a source-aware browser fetcher.
- The browser fetcher delegates only Joom URLs to a configured rendered-HTML provider.
- If no provider is configured, no browser strategy is created; the source should stay disabled or testing on servers where direct extraction fails.

The rendered HTML provider is a narrow HTTP contract controlled by environment variables. It posts a public product URL and an optional wait selector to an approved internal or vendor rendering service, then returns HTML to the existing extraction layer. API keys are environment-only and never logged.

## AliExpress Design

AliExpress stays disabled until a data source is selected and verified. Allowed options:

1. Official AliExpress Affiliate/Open Platform API, especially `aliexpress.affiliate.productdetail.get`, if valid credentials and terms are available.
2. Approved data provider such as Piloterr, Oxylabs, ScrapingBee, or Apify, with a documented contract and cost.
3. Leave disabled with `monitoring_unavailable` if no official/provider route is approved.

Direct scraping of the CAPTCHA/punish response is not implemented.

## Testing

Backend tests must cover:

- OpenGraph product meta extraction.
- Source-aware browser fetcher dispatch for Joom.
- HTTP rendered provider request/response contract with fake transport.
- Worker wiring of the source-aware browser fetcher.
- AliExpress documentation decision remains docs-only until credentials/provider are chosen.

No unit test may launch a real browser or call live marketplaces.
