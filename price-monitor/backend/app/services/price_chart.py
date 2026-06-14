from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.monitoring import (
    PriceHistory,
    TrackedProduct,
    UserProductSubscription,
)
from app.schemas.price_chart import (
    PriceChartLabels,
    PriceChartPoint,
    PriceChartResponse,
    PriceChartSummary,
    PriceChartYAxis,
)

MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class _ChartSourcePoint:
    ts: str
    price: Decimal
    currency: str


def current_utc_datetime() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def build_price_chart(
    session: Session,
    *,
    tracked_product_id: int,
    site_id: str,
    external_user_id: str,
    days: int = 30,
    granularity: str = "raw",
    currency: str | None = None,
) -> PriceChartResponse | None:
    tracked_product = _get_owned_active_product(
        session,
        tracked_product_id=tracked_product_id,
        site_id=site_id,
        external_user_id=external_user_id,
    )
    if tracked_product is None:
        return None

    history = _list_history_points(
        session,
        tracked_product_id=tracked_product_id,
        days=days,
        currency=currency,
    )
    chart_points = (
        _daily_points(history) if granularity == "daily" else _raw_points(history)
    )
    response_currency = _response_currency(
        requested_currency=currency,
        chart_points=chart_points,
        tracked_product=tracked_product,
    )
    summary = _summary(chart_points)

    return PriceChartResponse(
        tracked_product_id=tracked_product.id,
        title=tracked_product.product_name or "Товар",
        currency=response_currency,
        summary=summary,
        series=[
            PriceChartPoint(ts=point.ts, price=_format_money(point.price))
            for point in chart_points
        ],
        y_axis=PriceChartYAxis(
            min=summary.min_price,
            avg=summary.avg_price,
            max=summary.max_price,
        ),
        labels=PriceChartLabels(headline=_headline(summary)),
    )


def summarize_price_history(
    history: list[PriceHistory],
) -> tuple[PriceChartSummary, PriceChartLabels]:
    summary = _summary(_raw_points(history))
    return summary, PriceChartLabels(headline=_headline(summary))


def _get_owned_active_product(
    session: Session,
    *,
    tracked_product_id: int,
    site_id: str,
    external_user_id: str,
) -> TrackedProduct | None:
    statement = (
        select(TrackedProduct)
        .join(UserProductSubscription)
        .where(
            TrackedProduct.id == tracked_product_id,
            UserProductSubscription.site_id == site_id,
            UserProductSubscription.external_user_id == external_user_id,
            UserProductSubscription.tracked_product_id == tracked_product_id,
            UserProductSubscription.is_active.is_(True),
        )
    )
    return session.scalar(statement)


def _list_history_points(
    session: Session,
    *,
    tracked_product_id: int,
    days: int,
    currency: str | None,
) -> list[PriceHistory]:
    period_start = current_utc_datetime() - timedelta(days=days)
    statement = select(PriceHistory).where(
        PriceHistory.tracked_product_id == tracked_product_id,
        PriceHistory.fetched_at >= period_start,
    )
    if currency is not None:
        statement = statement.where(PriceHistory.currency == currency)

    statement = statement.order_by(PriceHistory.fetched_at.asc(), PriceHistory.id.asc())
    return list(session.scalars(statement))


def _raw_points(history: list[PriceHistory]) -> list[_ChartSourcePoint]:
    return [
        _ChartSourcePoint(
            ts=_format_instant(point.fetched_at),
            price=point.price_current,
            currency=point.currency,
        )
        for point in history
    ]


def _daily_points(history: list[PriceHistory]) -> list[_ChartSourcePoint]:
    points_by_day: dict[datetime.date, PriceHistory] = {}
    for point in history:
        points_by_day[_as_utc_naive(point.fetched_at).date()] = point

    return [
        _ChartSourcePoint(
            ts=_format_daily_instant(day),
            price=point.price_current,
            currency=point.currency,
        )
        for day, point in points_by_day.items()
    ]


def _summary(points: list[_ChartSourcePoint]) -> PriceChartSummary:
    if not points:
        return PriceChartSummary(
            current_price=None,
            avg_price=None,
            min_price=None,
            max_price=None,
            delta_vs_avg_percent=None,
            trend="no_data",
        )

    prices = [point.price for point in points]
    current_price = prices[-1]
    avg_price = sum(prices, Decimal("0")) / Decimal(len(prices))
    min_price = min(prices)
    max_price = max(prices)
    delta = ((current_price - avg_price) / avg_price * Decimal("100")).quantize(
        PERCENT_QUANT,
        rounding=ROUND_HALF_UP,
    )
    avg_price = avg_price.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    return PriceChartSummary(
        current_price=_format_money(current_price),
        avg_price=_format_money(avg_price),
        min_price=_format_money(min_price),
        max_price=_format_money(max_price),
        delta_vs_avg_percent=_format_percent(delta),
        trend=_trend(current_price, avg_price),
    )


def _trend(current_price: Decimal, avg_price: Decimal) -> str:
    if current_price > avg_price:
        return "above_usual"
    if current_price < avg_price:
        return "below_usual"
    return "near_average"


def _headline(summary: PriceChartSummary) -> str:
    if summary.trend == "no_data":
        return "Недостаточно данных для графика"
    if summary.trend == "near_average":
        return "Сейчас обычная цена"

    delta = Decimal(summary.delta_vs_avg_percent or "0").copy_abs()
    percent = _format_percent_for_label(delta)
    if summary.trend == "above_usual":
        return f"Сейчас дороже, чем обычно, на {percent}%"
    return f"Сейчас дешевле, чем обычно, на {percent}%"


def _response_currency(
    *,
    requested_currency: str | None,
    chart_points: list[_ChartSourcePoint],
    tracked_product: TrackedProduct,
) -> str:
    if requested_currency is not None:
        return requested_currency
    if chart_points:
        return chart_points[-1].currency
    return tracked_product.currency or "USD"


def _format_instant(value: datetime) -> str:
    return _as_utc_naive(value).isoformat(timespec="seconds") + "Z"


def _format_daily_instant(day: date) -> str:
    return datetime.combine(day, time.min).isoformat(timespec="seconds") + "Z"


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _format_money(value: Decimal) -> str:
    return f"{value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP):.2f}"


def _format_percent(value: Decimal) -> str:
    return f"{value.quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP):.2f}"


def _format_percent_for_label(value: Decimal) -> str:
    normalized = value.quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP).normalize()
    return format(normalized, "f")
