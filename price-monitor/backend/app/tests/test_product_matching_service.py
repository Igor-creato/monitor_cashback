from __future__ import annotations

from app.services.product_matching import (
    MatchThresholds,
    build_search_variants,
    normalize_product_text,
    score_product_match,
)


def test_normalize_product_text_cleans_noise_and_extracts_attributes() -> None:
    profile = normalize_product_text(
        "🔥 Смартфон Apple iPhone 15 Pro Max 256GB Blue Titanium "
        "SKU: A3108 EAN 4612345678901, 6.7\", новый!!! Купить со скидкой"
    )

    assert profile.cleaned_text == (
        "apple iphone 15 pro max 256gb blue titanium a3108 4612345678901 6.7"
    )
    assert profile.brand == "apple"
    assert profile.model == "iphone 15 pro max"
    assert profile.sku == "a3108"
    assert profile.barcode == "4612345678901"
    assert profile.size == "6.7"
    assert profile.color == "blue titanium"
    assert profile.memory == "256gb"
    assert profile.category == "phone"


def test_build_search_variants_prefers_specific_product_identity() -> None:
    profile = normalize_product_text("Samsung Galaxy S24 Ultra 12/512GB Black")

    assert build_search_variants(profile) == (
        "samsung galaxy s24 ultra 512gb black",
        "samsung galaxy s24 ultra 512gb",
        "samsung galaxy s24 ultra",
        "galaxy s24 ultra",
    )


def test_similar_models_are_likely_not_exact() -> None:
    target = normalize_product_text("Apple iPhone 15 Pro 256GB Black")
    candidate = normalize_product_text("Apple iPhone 15 Pro Max 256GB Black")

    decision = score_product_match(target, candidate, MatchThresholds())

    assert decision.status == "likely"
    assert decision.score < MatchThresholds().exact_threshold
    assert "model_variant_difference" in decision.explanation["signals"]


def test_different_memory_bundle_is_rejected() -> None:
    target = normalize_product_text("Apple iPhone 15 Pro 128GB Black")
    candidate = normalize_product_text("Apple iPhone 15 Pro 256GB Black")

    decision = score_product_match(target, candidate, MatchThresholds())

    assert decision.status == "rejected"
    assert decision.score == 0
    assert decision.explanation["reject_reason"] == "memory_mismatch"


def test_different_size_is_rejected() -> None:
    target = normalize_product_text("Nike Air Force 1 white EU 42")
    candidate = normalize_product_text("Nike Air Force 1 white EU 44")

    decision = score_product_match(target, candidate, MatchThresholds())

    assert decision.status == "rejected"
    assert decision.explanation["reject_reason"] == "size_mismatch"


def test_accessory_instead_of_product_is_rejected() -> None:
    target = normalize_product_text("Apple iPhone 15 Pro Max 256GB")
    candidate = normalize_product_text("Чехол для Apple iPhone 15 Pro Max MagSafe")

    decision = score_product_match(target, candidate, MatchThresholds())

    assert decision.status == "rejected"
    assert decision.explanation["reject_reason"] == "accessory_instead_of_product"
