from __future__ import annotations

from decimal import Decimal
from typing import Any

DISPLAY_POLICY_CASHBACK_UNAVAILABLE = "cashback_unavailable"
DISPLAY_POLICY_SHOW_EXACT_RATE = "show_exact_rate"
DISPLAY_POLICY_SHOW_RANGE_MIN = "show_range_use_min_for_effective_price"
DISPLAY_POLICY_SHOW_POSSIBLE = "show_possible_do_not_reduce_effective_price"
DISPLAY_POLICY_UNKNOWN = "cashback_unknown_requires_check"


def calculate_user_cashback(
    price: Decimal | int | str,
    commission_rate: Decimal | int | str,
    user_share: Decimal | int | str,
) -> Decimal:
    return (
        _to_decimal(price)
        * _to_decimal(commission_rate)
        / Decimal("100")
        * _to_decimal(user_share)
    )


def calculate_range_cashback(
    price: Decimal | int | str,
    commission_min: Decimal | int | str,
    commission_max: Decimal | int | str,
    user_share: Decimal | int | str,
) -> tuple[Decimal, Decimal]:
    return (
        calculate_user_cashback(price, commission_min, user_share),
        calculate_user_cashback(price, commission_max, user_share),
    )


def determine_display_policy(
    commission_exact: Decimal | int | str | None,
    commission_min: Decimal | int | str | None,
    commission_max: Decimal | int | str | None,
    cashback_status: str,
) -> str:
    if cashback_status == "no_partner":
        return DISPLAY_POLICY_CASHBACK_UNAVAILABLE
    if commission_exact is not None:
        return DISPLAY_POLICY_SHOW_EXACT_RATE
    if commission_min is not None and commission_max is not None:
        if _to_decimal(commission_min) == Decimal("0"):
            return DISPLAY_POLICY_SHOW_POSSIBLE
        return DISPLAY_POLICY_SHOW_RANGE_MIN
    return DISPLAY_POLICY_UNKNOWN


def normalize_cashback_resolution(
    response: dict[str, Any],
    price: Decimal | int | str,
) -> dict[str, Any]:
    cashback_status = str(response.get("cashback_status", "no_partner"))
    commission_exact = response.get("commission_exact")
    commission_min = response.get("commission_min")
    commission_max = response.get("commission_max")
    user_share = response.get("user_share")
    display_policy = determine_display_policy(
        commission_exact,
        commission_min,
        commission_max,
        cashback_status,
    )

    normalized = dict(response)
    normalized.update(
        {
            "cashback_status": cashback_status,
            "cashback_available": cashback_status != "no_partner",
            "display_policy": display_policy,
            "confidence": response.get(
                "confidence",
                _default_confidence(cashback_status, commission_exact, commission_min),
            ),
            "expected_cashback_exact": None,
            "expected_cashback_min": None,
            "expected_cashback_max": None,
            "effective_price": None,
            "effective_price_conservative": None,
        }
    )

    if cashback_status == "no_partner":
        return normalized

    if commission_exact is not None and user_share is not None:
        user_cashback = calculate_user_cashback(price, commission_exact, user_share)
        normalized["expected_cashback_exact"] = user_cashback
        normalized["effective_price"] = _to_decimal(price) - user_cashback
        return normalized

    if (
        commission_min is not None
        and commission_max is not None
        and user_share is not None
    ):
        min_cashback, max_cashback = calculate_range_cashback(
            price,
            commission_min,
            commission_max,
            user_share,
        )
        normalized["expected_cashback_min"] = min_cashback
        normalized["expected_cashback_max"] = max_cashback
        normalized["effective_price_conservative"] = (
            _to_decimal(price)
            if _to_decimal(commission_min) == Decimal("0")
            else _to_decimal(price) - min_cashback
        )

    return normalized


def _default_confidence(
    cashback_status: str,
    commission_exact: Any,
    commission_min: Any,
) -> str:
    if cashback_status == "no_partner":
        return "none"
    if commission_exact is not None:
        return "exact"
    if commission_min is not None:
        return "medium"
    return "none"


def _to_decimal(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value))
