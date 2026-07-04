from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_monitor.price_compare.feed import NormalizedOffer
from price_monitor.price_compare.feed_parsers import (
    parse_admitad_csv_feed,
    parse_admitad_xml_feed,
    parse_advcake_yml_feed,
)
from price_monitor.price_compare.models import (
    AffiliateFeedSource,
    FeedImportRun,
    Offer,
    PriceSnapshot,
    StoreSource,
)
from price_monitor.price_compare.wordpress_bridge import (
    WordPressInternalBridgeClient,
    redact_wordpress_bridge_payload,
)

_FEED_UPDATED_AT_KEYS = (
    "last_feed_updated_at",
    "feed_updated_at",
    "advertiser_last_update",
    "admitad_last_update",
    "last_update",
    "last_download",
    "updated_at",
)


class FeedBridge(Protocol):
    def feed_descriptors(self) -> dict[str, Any]: ...

    def download_feed(self, descriptor: dict[str, object]) -> bytes: ...


@dataclass(frozen=True, slots=True)
class FeedImportSummary:
    status: str
    created_count: int
    updated_count: int
    skipped_count: int
    quarantined_count: int


class AffiliateFeedImportService:
    def __init__(
        self,
        session: Session,
        *,
        bridge: FeedBridge | None = None,
        downloader: Callable[[str], bytes] | None = None,
    ) -> None:
        self._session = session
        self._bridge = bridge or WordPressInternalBridgeClient()
        self._downloader = downloader

    def import_configured_feeds(self) -> FeedImportSummary:
        descriptors = _descriptor_items(self._bridge.feed_descriptors())
        totals = _MutableCounts()
        failures = 0

        for descriptor in descriptors:
            feed_source = self._upsert_feed_source(descriptor)
            if feed_source is None:
                totals.skipped += 1
                failures += 1
                continue

            try:
                content = self._download_descriptor(descriptor)
                offers = list(_parse_descriptor(descriptor, content))
                counts = self._upsert_offers(descriptor, offers)
                self._record_run(feed_source, "success", counts)
                totals.add(counts)
            except Exception:
                failures += 1
                counts = _MutableCounts(skipped=1)
                self._record_run(
                    feed_source,
                    "failed",
                    counts,
                    error_code="feed_import_failed",
                    error_message="Feed import failed before offers were indexed.",
                )
                totals.add(counts)

        self._session.commit()
        return FeedImportSummary(
            status=_summary_status(descriptors, failures),
            created_count=totals.created,
            updated_count=totals.updated,
            skipped_count=totals.skipped,
            quarantined_count=totals.quarantined,
        )

    def _upsert_feed_source(self, descriptor: Mapping[str, object]) -> AffiliateFeedSource | None:
        network = _string(descriptor.get("network")).lower()
        store_domain = _normalize_domain(_string(descriptor.get("store_domain")))
        feed_id = _string(descriptor.get("feed_id")) or _string(descriptor.get("id"))
        if not network or not store_domain or not feed_id:
            return None

        offer_id = _string(descriptor.get("offer_id"))
        self._ensure_store(store_domain, _string(descriptor.get("store_name")) or store_domain)
        stmt = select(AffiliateFeedSource).where(
            AffiliateFeedSource.network == network,
            AffiliateFeedSource.store_domain == store_domain,
            AffiliateFeedSource.offer_id == offer_id,
            AffiliateFeedSource.feed_id == feed_id,
        )
        feed_source = self._session.scalar(stmt)
        if feed_source is None:
            feed_source = AffiliateFeedSource(
                network=network,
                store_domain=store_domain,
                offer_id=offer_id,
                feed_id=feed_id,
            )
            self._session.add(feed_source)

        feed_url = _string(descriptor.get("feed_url") or descriptor.get("url"))
        feed_source.display_name = (
            _string(descriptor.get("name") or descriptor.get("title")) or None
        )
        feed_source.format = _string(descriptor.get("format")).lower() or "xml"
        feed_source.feed_url_hash = _sha256_text(feed_url) if feed_url else None
        feed_source.feed_url_secret = bool(descriptor.get("feed_url_secret", True))
        feed_source.descriptor_payload = _safe_descriptor_payload(descriptor)
        feed_updated_at = _descriptor_updated_at(descriptor)
        if feed_updated_at is not None:
            feed_source.last_feed_updated_at = feed_updated_at
        feed_source.active = bool(descriptor.get("active", True))
        self._session.flush()
        return feed_source

    def _ensure_store(self, domain: str, display_name: str) -> None:
        store = self._session.scalar(select(StoreSource).where(StoreSource.domain == domain))
        if store is None:
            self._session.add(
                StoreSource(
                    domain=domain,
                    display_name=display_name,
                    active=True,
                    source_type="affiliate_feed",
                )
            )
            self._session.flush()

    def _download_descriptor(self, descriptor: dict[str, object]) -> bytes:
        if bool(descriptor.get("feed_url_secret", True)):
            return self._bridge.download_feed(descriptor)
        feed_url = _string(descriptor.get("feed_url") or descriptor.get("url"))
        if not feed_url or self._downloader is None:
            raise RuntimeError("feed downloader unavailable")
        return self._downloader(feed_url)

    def _upsert_offers(
        self, descriptor: Mapping[str, object], offers: list[NormalizedOffer]
    ) -> _MutableCounts:
        counts = _MutableCounts()
        store_domain = _normalize_domain(_string(descriptor.get("store_domain")))
        region_supported = bool(descriptor.get("region_supported", False))
        now = datetime.now(UTC)

        for offer in offers:
            stmt = select(Offer).where(
                Offer.source == offer.source,
                Offer.external_id == offer.external_id,
                Offer.url == offer.url,
            )
            existing = self._session.scalar(stmt)
            raw_hash = _offer_hash(offer)
            if existing is None:
                existing = Offer(
                    source=offer.source,
                    store_domain=store_domain or offer.store_domain,
                    external_id=offer.external_id,
                    title=offer.title,
                    normalized_title=_normalize_title(offer.title),
                    url=offer.url,
                )
                self._session.add(existing)
                counts.created += 1
            else:
                counts.updated += 1

            existing.title = offer.title
            existing.normalized_title = _normalize_title(offer.title)
            existing.image_url = offer.image_url
            existing.price = offer.price
            existing.currency = offer.currency
            existing.availability = offer.availability
            existing.region_supported = region_supported
            existing.city = _string(descriptor.get("city")) or None
            existing.category = offer.category
            existing.brand = offer.brand
            existing.raw_payload_hash = raw_hash
            existing.updated_at = now
            self._session.flush()
            self._session.add(
                PriceSnapshot(
                    offer_id=existing.id,
                    price=offer.price,
                    currency=offer.currency,
                    availability=offer.availability,
                    observed_at=now,
                )
            )

        return counts

    def _record_run(
        self,
        feed_source: AffiliateFeedSource,
        status: str,
        counts: _MutableCounts,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        self._session.add(
            FeedImportRun(
                feed_source_id=feed_source.id,
                status=status,
                started_at=now,
                finished_at=now,
                created_count=counts.created,
                updated_count=counts.updated,
                skipped_count=counts.skipped,
                quarantined_count=counts.quarantined,
                feed_updated_at=feed_source.last_feed_updated_at,
                error_code=error_code,
                error_message=error_message,
            )
        )


@dataclass(slots=True)
class _MutableCounts:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    quarantined: int = 0

    def add(self, other: _MutableCounts) -> None:
        self.created += other.created
        self.updated += other.updated
        self.skipped += other.skipped
        self.quarantined += other.quarantined


def _descriptor_items(payload: Mapping[str, Any]) -> list[dict[str, object]]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _parse_descriptor(descriptor: Mapping[str, object], content: bytes) -> list[NormalizedOffer]:
    network = _string(descriptor.get("network")).lower()
    format_name = _string(descriptor.get("format")).lower()
    store_domain = _normalize_domain(_string(descriptor.get("store_domain")))
    if network == "admitad" and format_name == "csv":
        return list(parse_admitad_csv_feed(content, store_domain=store_domain))
    if network == "admitad":
        return list(parse_admitad_xml_feed(content, store_domain=store_domain))
    if network == "advcake":
        return list(parse_advcake_yml_feed(content, store_domain=store_domain))
    return []


def _safe_descriptor_payload(descriptor: Mapping[str, object]) -> dict[str, object]:
    redacted = redact_wordpress_bridge_payload(dict(descriptor))
    return dict(redacted) if isinstance(redacted, dict) else {}


def _descriptor_updated_at(descriptor: Mapping[str, object]) -> datetime | None:
    for key in _FEED_UPDATED_AT_KEYS:
        parsed = _parse_datetime(descriptor.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _summary_status(descriptors: list[dict[str, object]], failures: int) -> str:
    if not descriptors:
        return "empty"
    if failures:
        return "partial"
    return "success"


def _offer_hash(offer: NormalizedOffer) -> str:
    payload = {
        "title": offer.title,
        "url": offer.url,
        "price": str(offer.price),
        "currency": offer.currency,
        "availability": offer.availability,
        "image_url": offer.image_url,
        "category": offer.category,
        "brand": offer.brand,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_title(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_domain(value: str) -> str:
    return value.strip().lower().removeprefix("www.")


def _string(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
