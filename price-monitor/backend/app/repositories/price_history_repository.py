from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import PriceHistory

MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.01")
PriceHistoryTrend = Literal["above_usual", "below_usual", "near_average", "no_data"]


@dataclass(frozen=True)
class PriceHistoryPoint:
    id: int | None
    tracked_product_id: int
    price_current: Decimal
    price_old: Decimal | None
    currency: str
    availability: bool
    seller_name: str | None
    fetched_at: datetime
    region_code: str = "default"


@dataclass(frozen=True)
class PriceHistoryChartSummary:
    current_price: Decimal | None
    avg_price: Decimal | None
    min_price: Decimal | None
    max_price: Decimal | None
    delta_vs_avg_percent: Decimal | None
    trend: PriceHistoryTrend


@runtime_checkable
class PriceHistoryRepository(Protocol):
    def write_price_point(
        self,
        *,
        tracked_product_id: int,
        region_code: str = "default",
        price_current: Decimal,
        price_old: Decimal | None,
        currency: str,
        availability: bool,
        seller_name: str | None,
        fetched_at: datetime,
    ) -> PriceHistoryPoint: ...

    def get_price_points(
        self,
        *,
        tracked_product_id: int,
        fetched_at_from: datetime,
        currency: str | None = None,
    ) -> list[PriceHistoryPoint]: ...

    def get_chart_summary(
        self,
        *,
        tracked_product_id: int,
        fetched_at_from: datetime,
        currency: str | None = None,
    ) -> PriceHistoryChartSummary: ...


class MariaDBPriceHistoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def write_price_point(
        self,
        *,
        tracked_product_id: int,
        region_code: str = "default",
        price_current: Decimal,
        price_old: Decimal | None,
        currency: str,
        availability: bool,
        seller_name: str | None,
        fetched_at: datetime,
    ) -> PriceHistoryPoint:
        row = PriceHistory(
            tracked_product_id=tracked_product_id,
            region_code=region_code,
            price_current=price_current,
            price_old=price_old,
            currency=currency,
            availability=availability,
            seller_name=seller_name,
            fetched_at=fetched_at,
        )
        self.session.add(row)
        self.session.flush()
        return _to_point(row)

    def get_price_points(
        self,
        *,
        tracked_product_id: int,
        fetched_at_from: datetime,
        currency: str | None = None,
    ) -> list[PriceHistoryPoint]:
        statement = select(PriceHistory).where(
            PriceHistory.tracked_product_id == tracked_product_id,
            PriceHistory.fetched_at >= fetched_at_from,
        )
        if currency is not None:
            statement = statement.where(PriceHistory.currency == currency)

        statement = statement.order_by(
            PriceHistory.fetched_at.asc(), PriceHistory.id.asc()
        )
        return [_to_point(row) for row in self.session.scalars(statement)]

    def get_chart_summary(
        self,
        *,
        tracked_product_id: int,
        fetched_at_from: datetime,
        currency: str | None = None,
    ) -> PriceHistoryChartSummary:
        points = self.get_price_points(
            tracked_product_id=tracked_product_id,
            fetched_at_from=fetched_at_from,
            currency=currency,
        )
        return _summary(points)


def get_price_history_repository(session: Session) -> PriceHistoryRepository:
    return MariaDBPriceHistoryRepository(session)


def _to_point(row: PriceHistory) -> PriceHistoryPoint:
    return PriceHistoryPoint(
        id=row.id,
        tracked_product_id=row.tracked_product_id,
        region_code=row.region_code,
        price_current=row.price_current,
        price_old=row.price_old,
        currency=row.currency,
        availability=row.availability,
        seller_name=row.seller_name,
        fetched_at=row.fetched_at,
    )


def _summary(points: list[PriceHistoryPoint]) -> PriceHistoryChartSummary:
    if not points:
        return PriceHistoryChartSummary(
            current_price=None,
            avg_price=None,
            min_price=None,
            max_price=None,
            delta_vs_avg_percent=None,
            trend="no_data",
        )

    prices = [point.price_current for point in points]
    current_price = prices[-1]
    avg_price = sum(prices, Decimal("0")) / Decimal(len(prices))
    min_price = min(prices)
    max_price = max(prices)
    delta = ((current_price - avg_price) / avg_price * Decimal("100")).quantize(
        PERCENT_QUANT,
        rounding=ROUND_HALF_UP,
    )
    avg_price = avg_price.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    return PriceHistoryChartSummary(
        current_price=current_price,
        avg_price=avg_price,
        min_price=min_price,
        max_price=max_price,
        delta_vs_avg_percent=delta,
        trend=_trend(current_price, avg_price),
    )


def _trend(current_price: Decimal, avg_price: Decimal) -> PriceHistoryTrend:
    if current_price > avg_price:
        return "above_usual"
    if current_price < avg_price:
        return "below_usual"
    return "near_average"
