from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

AVAILABILITY_SORT_RANK = {
    "in_stock": 0,
    "unknown": 1,
    "out_of_stock": 2,
}


@dataclass(frozen=True, slots=True)
class OfferSearchRow:
    id: str
    title: str
    store_domain: str
    price: Decimal
    availability: str = "unknown"


def sort_offers_by_price(offers: list[OfferSearchRow]) -> list[OfferSearchRow]:
    return sorted(
        offers,
        key=lambda offer: (
            AVAILABILITY_SORT_RANK.get(offer.availability, AVAILABILITY_SORT_RANK["unknown"]),
            offer.price,
            offer.store_domain,
            offer.title,
            offer.id,
        ),
    )
