from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from price_monitor.price_compare.models import (
    AffiliateFeedSource,
    FeedImportRun,
    Offer,
    StoreSource,
)
from price_monitor.price_compare.search import AVAILABILITY_SORT_RANK

AFFILIATE_OFFER_SOURCE_NETWORKS = {
    "admitad_product_feed": "admitad",
    "advcake_product_feed": "advcake",
}


@dataclass(frozen=True, slots=True)
class OfferSearchResults:
    items: list[Offer]
    total: int


@dataclass(frozen=True, slots=True)
class SearchIndexState:
    active_store_count: int
    active_offer_count: int


@dataclass(frozen=True, slots=True)
class StoreSearchStatus:
    store_domain: str
    status: str
    offer_count: int
    region_supported: bool


@dataclass(frozen=True, slots=True)
class OfferFeedFreshness:
    store_domain: str
    offer_source: str
    network: str
    feed_updated_at: datetime | None
    import_finished_at: datetime | None
    import_status: str | None


class OfferRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def search(
        self, *, query: str, city: str, stores: list[str], limit: int, offset: int
    ) -> OfferSearchResults:
        del city
        stmt = (
            select(Offer)
            .join(StoreSource, StoreSource.domain == Offer.store_domain)
            .where(StoreSource.active.is_(True))
        )
        normalized_stores = [_normalize_domain(store) for store in stores if store.strip()]
        if normalized_stores:
            stmt = stmt.where(Offer.store_domain.in_(normalized_stores))

        for token in _normalize_query(query).split():
            stmt = stmt.where(Offer.normalized_title.contains(token))

        total = self._count(stmt)
        offers = list(self._session.scalars(stmt).all())
        sorted_offers = sorted(offers, key=_offer_sort_key)
        return OfferSearchResults(items=sorted_offers[offset : offset + limit], total=total)

    def index_state(self, *, stores: list[str]) -> SearchIndexState:
        normalized_stores = [_normalize_domain(store) for store in stores if store.strip()]
        store_stmt = select(StoreSource.domain).where(StoreSource.active.is_(True))
        if normalized_stores:
            store_stmt = store_stmt.where(StoreSource.domain.in_(normalized_stores))

        active_domains = list(self._session.scalars(store_stmt).all())
        if not active_domains:
            return SearchIndexState(active_store_count=0, active_offer_count=0)

        offer_count = (
            self._session.scalar(
                select(func.count())
                .select_from(Offer)
                .where(Offer.store_domain.in_(active_domains))
            )
            or 0
        )

        return SearchIndexState(
            active_store_count=len(active_domains),
            active_offer_count=offer_count,
        )

    def store_statuses(self, *, stores: list[str]) -> list[StoreSearchStatus]:
        normalized_stores = [_normalize_domain(store) for store in stores if store.strip()]
        stmt = select(StoreSource).where(StoreSource.active.is_(True))
        if normalized_stores:
            stmt = stmt.where(StoreSource.domain.in_(normalized_stores))
        sources = list(self._session.scalars(stmt).all())
        statuses: list[StoreSearchStatus] = []
        for source in sources:
            offer_count = (
                self._session.scalar(
                    select(func.count())
                    .select_from(Offer)
                    .where(Offer.store_domain == source.domain)
                )
                or 0
            )
            statuses.append(
                StoreSearchStatus(
                    store_domain=source.domain,
                    status="indexed" if offer_count else "empty",
                    offer_count=offer_count,
                    region_supported=source.supports_region,
                )
            )
        return statuses

    def feed_freshness_for_offers(
        self, offers: list[Offer]
    ) -> dict[tuple[str, str], OfferFeedFreshness]:
        freshness: dict[tuple[str, str], OfferFeedFreshness] = {}
        for offer in offers:
            network = AFFILIATE_OFFER_SOURCE_NETWORKS.get(offer.source)
            if network is None:
                continue
            key = (offer.store_domain, offer.source)
            if key in freshness:
                continue

            feed_sources = list(
                self._session.scalars(
                    select(AffiliateFeedSource).where(
                        AffiliateFeedSource.store_domain == offer.store_domain,
                        AffiliateFeedSource.network == network,
                        AffiliateFeedSource.active.is_(True),
                    )
                ).all()
            )
            if not feed_sources:
                continue

            feed_updated_at = max(
                (
                    feed_source.last_feed_updated_at
                    for feed_source in feed_sources
                    if feed_source.last_feed_updated_at is not None
                ),
                default=None,
            )
            feed_source_ids = [feed_source.id for feed_source in feed_sources]
            latest_run = self._session.scalars(
                select(FeedImportRun)
                .where(FeedImportRun.feed_source_id.in_(feed_source_ids))
                .order_by(FeedImportRun.finished_at.desc(), FeedImportRun.id.desc())
            ).first()

            freshness[key] = OfferFeedFreshness(
                store_domain=offer.store_domain,
                offer_source=offer.source,
                network=network,
                feed_updated_at=(
                    latest_run.feed_updated_at
                    if latest_run is not None and latest_run.feed_updated_at is not None
                    else feed_updated_at
                ),
                import_finished_at=latest_run.finished_at if latest_run is not None else None,
                import_status=latest_run.status if latest_run is not None else None,
            )
        return freshness

    def _count(self, stmt: Select[tuple[Offer]]) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return self._session.scalar(count_stmt) or 0


def _offer_sort_key(offer: Offer) -> tuple[int, Decimal, str, str, str]:
    price = offer.price if offer.price is not None else Decimal("Infinity")
    return (
        AVAILABILITY_SORT_RANK.get(offer.availability, AVAILABILITY_SORT_RANK["unknown"]),
        price,
        offer.store_domain,
        offer.title,
        offer.external_id,
    )


def _normalize_query(query: str) -> str:
    return " ".join(query.strip().lower().split())


def _normalize_domain(domain: str) -> str:
    return domain.strip().lower().removeprefix("www.")
