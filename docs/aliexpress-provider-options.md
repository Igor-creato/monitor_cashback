# AliExpress Provider Options

Date: 2026-07-02

## Current Runtime Finding

Direct backend HTTP fetch of `https://aliexpress.ru/item/1005010654381286.html`
returns a small AliExpress punish/CAPTCHA page. The backend now classifies this
as `captcha_detected`. A production AliExpress source should use either an
official/partner API or an approved managed fetching strategy with explicit
budgeting, source-level rate limits, diagnostics, and secret redaction.

## Option 1: Official AliExpress Affiliate API

Candidate endpoint: `aliexpress.affiliate.productdetail.get`.

Reference:

- https://developer.alibaba.com/docs/api.htm?apiId=48595
- https://developer.alibaba.com/docs/doc.htm?articleId=48595&docType=2&treeId=674

What it can provide:

- `product_id`
- `product_title`
- `product_main_image_url`
- `sale_price`
- `sale_price_currency`
- `target_sale_price`
- `target_sale_price_currency`
- `product_detail_url`
- `promotion_link`

Required before implementation:

- AliExpress/Open Platform app key and app secret.
- Affiliate tracking ID.
- Confirmation that the account can call `aliexpress.affiliate.productdetail.get` for the target country and currency.
- Real smoke against representative `aliexpress.ru` / `aliexpress.com` item URLs.
- Legal/product confirmation that affiliate API data can be used for price monitoring.

Pros:

- Official/partner route.
- Returns structured product and price fields.
- Avoids direct challenge handling in the monitored-source adapter.

Cons:

- Access and signing are account-dependent.
- Some documentation surfaces mark older Affiliate API material as deprecated.
- It may not return every public product or every localized marketplace URL.

Recommendation: try this first if valid affiliate credentials are available.

## Option 2: Piloterr AliExpress Product API

Endpoint: `/v2/aliexpress/product`.

Reference:

- https://www.piloterr.com/library/aliexpress-product

What it provides:

- Product page URL input.
- Browser-rendered structured JSON.
- Pricing, title, media, seller, stock-ish and delivery fields.
- Clear per-request pricing unit in credits.

Pros:

- Closest fit for a single product URL monitor.
- Structured JSON reduces parser drift.
- Explicitly documents AliExpress product pages as JavaScript SPAs.

Cons:

- Paid external provider.
- Requires API key and provider data-processing review.
- Output contract must be mapped and tested before production.

Recommendation: best provider candidate if official API is unavailable or incomplete.

## Option 3: Oxylabs Web Scraper API

Reference:

- https://oxylabs.io/products/scraper-api/ecommerce/aliexpress

What it provides:

- AliExpress public product data including titles, descriptions, prices, images, ratings, reviews, shipping, seller details, and inventory quantity.
- JavaScript rendering and anti-blocking infrastructure.
- Free trial and result-based billing.

Pros:

- Mature enterprise provider.
- Good fit when scale, support, and compliance paperwork matter.
- Can return raw HTML or structured output depending on plan/configuration.

Cons:

- More general-purpose than Piloterr's product endpoint.
- Higher vendor setup overhead.
- Contract and pricing should be confirmed with the account manager for the exact AliExpress PDP use case.

Recommendation: best enterprise/provider option.

## Option 4: ScrapingBee AliExpress API

Reference:

- https://www.scrapingbee.com/scrapers/aliexpress-api/

What it provides:

- AliExpress search, product, review, store and category pages through one API.
- JavaScript rendering, residential proxy rotation, and structured extraction rules.

Pros:

- Simple API surface and developer-friendly docs.
- Useful if we want one provider for multiple marketplace surfaces.

Cons:

- Credit multiplier can make rendered/stealth requests more expensive.
- AI/extraction-rule output needs stricter validation before storing prices.

Recommendation: viable developer-friendly fallback after Piloterr/Oxylabs.

## Option 5: Keep Disabled

If no official API or approved provider is selected, keep `aliexpress.ru` disabled in `monitored_sources`.

User-facing result:

- `GET /api/v1/sources/supported` returns `monitoring_unavailable`.
- WordPress shows `Для данного магазина мониторинг временно недоступен.`

Recommendation: safe default until credentials, budget, and provider terms are approved.

## Implementation Decision

Do not implement a live AliExpress integration in this branch. The next implementation step should be one of:

1. Official API adapter after credentials are available.
2. Piloterr provider adapter after API key and sample response are approved.
3. Oxylabs/ScrapingBee provider adapter after provider selection.
