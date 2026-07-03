from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from price_monitor.price_compare.models import Offer, StoreSource
from price_monitor.price_compare.search import AVAILABILITY_SORT_RANK


@dataclass(frozen=True, slots=True)
class OfferSearchResults:
    items: list[Offer]
    total: int


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
