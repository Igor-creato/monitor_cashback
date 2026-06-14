# Frontend Price Chart Spec

## Purpose

This document fixes the contract for the future WordPress/My Account price
chart. It describes how the frontend should consume and render the existing
price chart data without implementing WordPress frontend code in this service.

## Endpoint

Use the existing price-monitor endpoint through a WordPress proxy:

```http
GET /v1/products/{tracked_product_id}/price-chart
```

Expected query params:

- `site_id` - WordPress site identifier.
- `external_user_id` - user identity from WordPress.
- `days` - optional, default `30`, maximum `90`.
- `granularity` - optional, `raw` or `daily`.
- `currency` - optional filter by `price_history.currency`.

The browser must not call the price-monitor microservice directly. WordPress
must proxy the request server-side and sign the upstream request with the
existing HMAC mechanism.

## Rendering

The chart should render as a compact personal-account widget:

- main price line from `series[].price`;
- horizontal average line from `summary.avg_price` / `y_axis.avg`;
- visible labels for current, average, minimum, and maximum price;
- X axis formatted with Russian dates, for example `25 мая`, `26 мая`;
- Y axis formatted with the response `currency`;
- headline from `labels.headline`, for example
  `Сейчас дороже, чем обычно, на 6.25%`.

Recommended libraries:

- `uPlot` for a lightweight, fast chart with minimal bundle cost;
- `ECharts` if the UI needs richer tooltips, animations, or advanced visual
  interactions.

## States

- `loading` - show a skeleton or spinner while WordPress proxy request is in
  progress.
- `no_data` - when `series` is empty or `summary.trend` is `no_data`; show
  `labels.headline` and do not render a misleading line.
- `error` - when the WordPress proxy or upstream request fails; show a safe
  retry/error message without exposing internal details.
- `single_point` - when `series.length === 1`; render a single marker and
  current price label instead of implying a trend line.
- `normal` - when there are at least two points; render the line, average line,
  labels, axes, and headline.

## Security Requirements

- Do not fetch the microservice from browser JavaScript directly; use only the
  WordPress proxy endpoint.
- Do not expose the HMAC secret, signed headers, service URL, or internal
  authentication details to the browser.
- Do not trust values read from DOM attributes or inline data without escaping.
- Render product titles, headline text, currency, and formatted dates with the
  frontend framework's normal escaping or WordPress-safe escaping helpers.
- Do not add marketplace fetches, cashback internal API calls, or captcha
  bypass logic in the chart frontend.

## Example Response

```json
{
  "tracked_product_id": 1,
  "title": "Palit Видеокарта GeForce RTX 5070",
  "currency": "USD",
  "summary": {
    "current_price": "850.00",
    "avg_price": "800.00",
    "min_price": "750.00",
    "max_price": "850.00",
    "delta_vs_avg_percent": "6.25",
    "trend": "above_usual"
  },
  "series": [
    { "ts": "2026-05-25T10:00:00Z", "price": "750.00" },
    { "ts": "2026-05-26T10:00:00Z", "price": "800.00" },
    { "ts": "2026-05-27T10:00:00Z", "price": "850.00" }
  ],
  "y_axis": {
    "min": "750.00",
    "avg": "800.00",
    "max": "850.00"
  },
  "labels": {
    "headline": "Сейчас дороже, чем обычно, на 6.25%"
  }
}
```

## Expected Visual Behavior

In the normal state, the widget should show the headline above the chart, then a
single price line across the selected period. The average price should appear as
a subtle horizontal reference line. Current, average, minimum, and maximum
values should be visible near the chart or in a compact summary row.

For `above_usual`, the headline should communicate that the current price is
higher than usual. For `below_usual`, it should communicate that the current
price is lower than usual. For `near_average`, the widget should avoid alarming
styling and show that the price is close to the average. For `no_data`, the
widget should avoid rendering an empty axis-only chart.
