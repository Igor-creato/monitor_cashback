from decimal import Decimal

from app.services.cashback_calculation import (
    calculate_range_cashback,
    calculate_user_cashback,
    determine_display_policy,
    normalize_cashback_resolution,
)


def test_no_partner_does_not_calculate_effective_price() -> None:
    result = normalize_cashback_resolution(
        {"cashback_status": "no_partner", "confidence": "none"},
        Decimal("1000.00"),
    )

    assert result["cashback_available"] is False
    assert result["effective_price"] is None
    assert result["effective_price_conservative"] is None
    assert result["display_policy"] == "cashback_unavailable"
    assert result["confidence"] == "none"


def test_exact_rate_calculates_user_cashback_and_effective_price() -> None:
    result = normalize_cashback_resolution(
        {
            "cashback_status": "partner_exact",
            "commission_exact": "10",
            "user_share": "0.5",
        },
        Decimal("1000.00"),
    )

    assert result["cashback_available"] is True
    assert result["expected_cashback_exact"] == Decimal("50.000")
    assert result["effective_price"] == Decimal("950.000")
    assert result["effective_price_conservative"] is None
    assert result["display_policy"] == "show_exact_rate"
    assert result["confidence"] == "exact"


def test_range_rate_calculates_min_and_max_user_cashback() -> None:
    min_cashback, max_cashback = calculate_range_cashback(
        Decimal("1000.00"),
        "5",
        "12",
        "0.5",
    )

    assert min_cashback == Decimal("25.000")
    assert max_cashback == Decimal("60.000")


def test_range_uses_min_for_conservative_effective_price() -> None:
    result = normalize_cashback_resolution(
        {
            "cashback_status": "partner_estimated",
            "commission_min": "5",
            "commission_max": "12",
            "user_share": "0.5",
        },
        Decimal("1000.00"),
    )

    assert result["expected_cashback_min"] == Decimal("25.000")
    assert result["expected_cashback_max"] == Decimal("60.000")
    assert result["effective_price"] is None
    assert result["effective_price_conservative"] == Decimal("975.000")
    assert result["display_policy"] == "show_range_use_min_for_effective_price"
    assert result["confidence"] == "medium"


def test_zero_min_rate_does_not_reduce_conservative_effective_price() -> None:
    result = normalize_cashback_resolution(
        {
            "cashback_status": "partner_estimated",
            "commission_min": "0",
            "commission_max": "12",
            "user_share": "0.5",
        },
        Decimal("1000.00"),
    )

    assert result["expected_cashback_min"] == Decimal("0.000")
    assert result["expected_cashback_max"] == Decimal("60.000")
    assert result["effective_price_conservative"] == Decimal("1000.00")
    assert result["display_policy"] == "show_possible_do_not_reduce_effective_price"


def test_max_rate_is_not_used_for_conservative_effective_price() -> None:
    result = normalize_cashback_resolution(
        {
            "cashback_status": "partner_estimated",
            "commission_min": "1",
            "commission_max": "90",
            "user_share": "0.5",
        },
        Decimal("1000.00"),
    )

    assert result["expected_cashback_max"] == Decimal("450.000")
    assert result["effective_price_conservative"] == Decimal("995.000")


def test_user_share_is_applied_to_cashback_calculation() -> None:
    full_share = calculate_user_cashback(Decimal("1000.00"), "10", "1")
    half_share = calculate_user_cashback(Decimal("1000.00"), "10", "0.5")

    assert full_share == Decimal("100.00")
    assert half_share == Decimal("50.000")


def test_display_policy_is_determined_from_available_rates() -> None:
    assert (
        determine_display_policy("10", None, None, "partner_exact") == "show_exact_rate"
    )
    assert (
        determine_display_policy(None, "5", "12", "partner_estimated")
        == "show_range_use_min_for_effective_price"
    )
    assert (
        determine_display_policy(None, "0", "12", "partner_estimated")
        == "show_possible_do_not_reduce_effective_price"
    )
    assert (
        determine_display_policy(None, None, None, "no_partner")
        == "cashback_unavailable"
    )
