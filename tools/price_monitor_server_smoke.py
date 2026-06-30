"""Run signed price-monitor smoke checks inside the API container."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import select

from price_monitor.core.config import get_settings
from price_monitor.core.security import build_signed_headers
from price_monitor.db.session import get_session_factory
from price_monitor.domains.fetching.ports import FetchPageResult
from price_monitor.domains.fetching.service import FetchPipeline
from price_monitor.domains.reliability.models import AlertEvent, OutboxEvent
from price_monitor.domains.watchlist.models import WatchlistItem

BASE_URL = "http://127.0.0.1:8000"


class ControlledFetcher:
    def __init__(self, *, title: str, price: str) -> None:
        self._html = f"""
        <html><head>
        <script type="application/ld+json">
        {{"@type":"Product","name":"{title}","image":"https://example.com/image.jpg","aggregateRating":{{"ratingValue":"4.8"}},"offers":{{"price":"{price}","priceCurrency":"RUB"}}}}
        </script>
        </head><body></body></html>
        """

    def fetch(self, *, url: str, proxy_url: str | None) -> FetchPageResult:
        del proxy_url
        return FetchPageResult(
            content=self._html,
            final_url=url,
            http_status=200,
            response_ms=7,
        )


def main() -> None:
    secrets = get_settings().hmac_secret_list
    if not secrets:
        raise RuntimeError("PRICE_MONITOR_HMAC_SECRETS is empty")
    secret = secrets[0]
    run_id = f"task10-{uuid4().hex[:12]}"
    cleanup_items: list[tuple[str, str]] = []
    original_limit: int | None = None
    smoke_limit: int | None = None
    restored_limit = "not_needed"

    def call(
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        query = urlencode(sorted((params or {}).items())) if params else None
        url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
        body = (
            b""
            if payload is None
            else json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        )
        headers = build_signed_headers(
            secret=secret,
            method=method,
            path=path,
            query=query if method.upper() == "GET" else None,
            body=body,
            request_id=request_id or f"{run_id}-{uuid4().hex[:8]}",
        )
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key

        req = Request(  # noqa: S310 - fixed local API smoke target.
            url,
            data=None if method.upper() == "GET" else body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(req, timeout=10) as response:  # noqa: S310
                raw = response.read()
                parsed = _parse_response(raw)
                return {"status": response.status, "json": parsed}
        except HTTPError as exc:
            raw = exc.read()
            parsed = _parse_response(raw)
            return {"status": exc.code, "json": parsed}

    def assert_status(result: dict[str, Any], status: int, label: str) -> None:
        if result["status"] != status:
            raise AssertionError(
                f"{label}: expected {status}, got {result['status']} {result['json']}"
            )

    def assert_error(result: dict[str, Any], status: int, code: str, label: str) -> None:
        assert_status(result, status, label)
        actual = result["json"].get("error", {}).get("code")
        if actual != code:
            raise AssertionError(f"{label}: expected {code}, got {actual} {result['json']}")

    def cleanup_watchlist_item(user_id: str, item_id: str) -> None:
        call(
            "DELETE",
            f"/api/v1/watchlist/items/{item_id}",
            payload={"user_id": user_id},
            idempotency_key=f"{run_id}-cleanup-{item_id}",
        )

    summary: dict[str, Any] = {"run_id": run_id}
    try:
        source = call(
            "POST",
            "/api/v1/admin/sources",
            payload={
                "source_domain": "example.com",
                "display_name": "Task 10 Smoke Example",
                "logo_url": "https://example.com/smoke-logo.png",
                "status": "active",
                "fetch_interval_hours": 6,
                "history_retention_days": 90,
                "browser_fallback_allowed": False,
                "proxy_pool_id": None,
            },
            idempotency_key=f"{run_id}-source",
        )
        assert_status(source, 201, "add supported source")
        summary["source"] = source["json"]["source"]["source_domain"]

        unsupported = call(
            "POST",
            "/api/v1/watchlist/items",
            payload={
                "user_id": f"{run_id}-unsupported",
                "url": f"https://unsupported-{run_id}.test/item",
                "target_price_minor": None,
                "currency": "RUB",
            },
            idempotency_key=f"{run_id}-unsupported",
        )
        assert_error(unsupported, 422, "unsupported_store", "unsupported source")

        user_id = f"{run_id}-user"
        product_url = f"https://example.com/products/{run_id}"
        created = call(
            "POST",
            "/api/v1/watchlist/items",
            payload={
                "user_id": user_id,
                "url": product_url,
                "target_price_minor": 13_000,
                "currency": "RUB",
            },
            idempotency_key=f"{run_id}-watch-create",
        )
        assert_status(created, 201, "create watchlist item")
        item = created["json"]["item"]
        item_id = item["id"]
        product_id = item["product_id"]
        summary["watchlist_item_id"] = item_id
        summary["product_id"] = product_id

        duplicate = call(
            "POST",
            "/api/v1/watchlist/items",
            payload={
                "user_id": user_id,
                "url": product_url,
                "target_price_minor": 13_000,
                "currency": "RUB",
            },
            idempotency_key=f"{run_id}-watch-duplicate",
        )
        assert_error(duplicate, 409, "duplicate_watchlist_item", "duplicate watchlist item")

        settings = call("GET", "/api/v1/admin/settings")
        assert_status(settings, 200, "read settings")
        original_limit = int(settings["json"]["settings"]["max_tracked_products_per_user"])
        smoke_limit = original_limit
        if smoke_limit > 12:
            smoke_limit = 3
            patched = call(
                "PATCH",
                "/api/v1/admin/settings",
                payload={"max_tracked_products_per_user": smoke_limit},
                idempotency_key=f"{run_id}-settings-down",
            )
            assert_status(patched, 200, "temporarily lower max tracked products")

        limit_user = f"{run_id}-limit"
        for index in range(smoke_limit):
            limited = call(
                "POST",
                "/api/v1/watchlist/items",
                payload={
                    "user_id": limit_user,
                    "url": f"https://example.com/products/{run_id}-limit-{index}",
                    "target_price_minor": None,
                    "currency": "RUB",
                },
                idempotency_key=f"{run_id}-limit-{index}",
            )
            assert_status(limited, 201, f"fill limit slot {index}")
            cleanup_items.append((limit_user, limited["json"]["item"]["id"]))

        limit_exceeded = call(
            "POST",
            "/api/v1/watchlist/items",
            payload={
                "user_id": limit_user,
                "url": f"https://example.com/products/{run_id}-limit-over",
                "target_price_minor": None,
                "currency": "RUB",
            },
            idempotency_key=f"{run_id}-limit-over",
        )
        assert_error(limit_exceeded, 409, "limit_exceeded", "limit exceeded")
        summary["limit_checked_at"] = smoke_limit

        now = datetime.now(UTC)
        with get_session_factory()() as session:
            fetch_result = FetchPipeline(
                session,
                direct_fetcher=ControlledFetcher(
                    title=f"Task 10 Smoke Product {run_id}",
                    price="123.45",
                ),
            ).run(product_id=product_id, now=now)
            if fetch_result.status != "ok" or fetch_result.price_point_id is None:
                raise AssertionError(f"fetch pipeline failed: {fetch_result}")

            alert = session.scalar(
                select(AlertEvent)
                .where(AlertEvent.watchlist_item_id == item_id)
                .order_by(AlertEvent.created_at.desc())
            )
            if alert is None:
                raise AssertionError("alert event was not created")

            outbox = session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == alert.id,
                    OutboxEvent.event_type == "notification.price_target_reached",
                )
            )
            if outbox is None:
                raise AssertionError("notification outbox event was not created")

            session.commit()
            summary["fetch_status"] = fetch_result.status
            summary["price_point_id"] = fetch_result.price_point_id
            summary["fetch_attempt_id"] = fetch_result.fetch_attempt_id
            summary["alert_event_id"] = alert.id
            summary["outbox_event_id"] = outbox.id

        product_card = call("GET", f"/api/v1/products/{product_id}")
        assert_status(product_card, 200, "product card")
        product = product_card["json"]["product"]
        if product["title"] != f"Task 10 Smoke Product {run_id}":
            raise AssertionError(f"product title was not hydrated: {product}")
        if product["current_price_minor"] != 12_345 or product["last_fetch_status"] != "ok":
            raise AssertionError(f"product price/status was not hydrated: {product}")

        chart = call("GET", f"/api/v1/products/{product_id}/price-chart", params={"days": 30})
        assert_status(chart, 200, "price chart")
        if not chart["json"].get("points"):
            raise AssertionError(f"price chart has no points: {chart['json']}")
        summary["chart_points"] = len(chart["json"]["points"])

        deleted = call(
            "DELETE",
            f"/api/v1/watchlist/items/{item_id}",
            payload={"user_id": user_id},
            idempotency_key=f"{run_id}-watch-delete",
        )
        assert_status(deleted, 204, "delete watchlist item")

        with get_session_factory()() as session:
            deleted_item = session.get(WatchlistItem, item_id)
            if deleted_item is None or deleted_item.status != "deleted":
                raise AssertionError("watchlist item was not marked deleted")
            if session.get(type(deleted_item.product), product_id) is None:
                raise AssertionError("product was removed during delete")
            summary["delete_status"] = deleted_item.status

        summary["result"] = "passed"
    finally:
        for cleanup_user_id, cleanup_item_id in cleanup_items:
            cleanup_watchlist_item(cleanup_user_id, cleanup_item_id)
        if original_limit is not None and smoke_limit is not None and smoke_limit != original_limit:
            restored = call(
                "PATCH",
                "/api/v1/admin/settings",
                payload={"max_tracked_products_per_user": original_limit},
                idempotency_key=f"{run_id}-settings-restore",
            )
            restored_limit = "yes" if restored["status"] == 200 else "failed"
        summary["settings_restored"] = restored_limit

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _parse_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    text = raw.decode(errors="replace")
    try:
        parsed = json.loads(text)
    except JSONDecodeError:
        return {"_raw": text[:500]}
    if isinstance(parsed, dict):
        return parsed
    return {"_json": parsed}


if __name__ == "__main__":
    main()
