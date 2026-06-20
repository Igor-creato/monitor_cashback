# Notification Deduplication and Rate Limits Decision

Date: 2026-06-20
Status: ADR-first gate for backend implementation

## Decision

Price Monitor notification delivery is backend-owned for event generation,
deduplication, cooldowns, preferences, and retry state. WordPress remains the
email notification layer. The backend sends only a minimal, HMAC-signed internal
notification contract to WordPress and never includes marketplace session data,
cookies, tokens, ciphertext, raw cart pages, or payment data.

The initial delivery channel is `email`. Notification rows use a channel-aware
deduplication key so the same event can later be delivered to `push` without
changing event identity or rewriting existing price-alert logic.

## Event Identity

Each notification event has:

- `event_type`
- `channel`
- `site_id`
- `external_user_id`
- `dedup_key`

The unique identity is
`site_id + external_user_id + event_type + channel + dedup_key`.

Product-level events use subscription/product/window data in `dedup_key`.
Connection-level events use connection/status/reason data in `dedup_key`.

## Cooldown, Preferences, and Daily Limits

User preferences are stored in `notification_preferences` by
`site_id + external_user_id + event_type + channel`.

Defaults:

- `enabled = true`
- `cooldown_minutes = 1440`
- `drop_threshold_percent = 5.00`

If a preference disables an event/channel, the backend does not create a
notification row. If an event is inside cooldown, the backend does not create a
duplicate row.

Daily limits use the existing WordPress price-monitor limits contract:
`limits.alerts_per_day`. Events with status `pending` or `sent` count toward the
UTC-day limit. If the limit is `0` or exhausted, the backend creates a
`skipped` event so admin diagnostics can explain suppression without attempting
delivery.

## WordPress Delivery Contract

Backend sends email notifications to:

```text
POST /wp-json/savello-internal/v1/price-monitor/notifications
```

The request is signed with the existing `CashbackAPIClient` HMAC headers.

Payload:

```json
{
  "notification_id": 123,
  "event_type": "target_price_reached",
  "channel": "email",
  "site_id": "savelloclub.ru",
  "external_user_id": "wp:savelloclub.ru:123",
  "dedup_key": "subscription:1:target_price_reached:900.00",
  "template": "price_monitor_target_price_reached",
  "subject_data": {},
  "body_data": {},
  "created_at": "2026-06-20T12:00:00Z"
}
```

Expected WordPress response:

- `{"status":"queued"}`
- `{"status":"sent"}`

Network and 5xx failures remain retryable. Authentication, 4xx, and malformed
responses are terminal failures. Failed retryable rows retain safe error labels
only.

## Reconnect and Sync Failure Notifications

`reconnect_required` is emitted when the existing marketplace connection state
machine moves a connection to `reconnect_required`.

`sync_failed_repeated` is emitted when a connection has at least three latest
consecutive failed sync sessions. This is a notification concern only; it does
not add new connection states or change retry/backoff policy.

## Explicit Non-Goals

This ADR does not implement WordPress plugin code, public FastAPI endpoints,
push delivery, marketplace adapters, captcha bypass, frontend UI, new login
flows, or collection of marketplace passwords.
