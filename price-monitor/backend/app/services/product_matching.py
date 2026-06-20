from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.secret_redaction import strip_secret_like_keys
from app.models.monitoring import (
    ProductFeedItem,
    ProductFeedSource,
    ProductMatchGroup,
    ProductOffer,
    Store,
    StoreSource,
    TrackedProduct,
)

MatchStatus = Literal["exact", "likely", "weak", "rejected"]

_BRANDS = {
    "apple",
    "samsung",
    "xiaomi",
    "redmi",
    "poco",
    "huawei",
    "honor",
    "nike",
    "adidas",
    "sony",
    "lg",
}
_COLORS = {
    "black",
    "white",
    "blue",
    "blue titanium",
    "titanium",
    "silver",
    "gold",
    "green",
    "red",
    "pink",
    "purple",
    "gray",
    "grey",
    "yellow",
    "orange",
}
_COLOR_ALIASES = {
    "черный": "black",
    "чёрный": "black",
    "белый": "white",
    "синий": "blue",
    "голубой": "blue",
    "серый": "gray",
    "серебристый": "silver",
    "золотой": "gold",
}
_NOISE_WORDS = {
    "смартфон",
    "телефон",
    "новый",
    "новыи",
    "купить",
    "скидкой",
    "скидкои",
    "скидка",
    "со",
    "с",
    "для",
    "sku",
    "ean",
    "gtin",
    "barcode",
    "оригинал",
    "original",
    "new",
    "sale",
}
_ACCESSORY_WORDS = {
    "case",
    "cover",
    "charger",
    "adapter",
    "glass",
    "protector",
    "чехол",
    "зарядка",
    "адаптер",
    "стекло",
    "защитное",
}
_PHONE_WORDS = {"iphone", "galaxy", "смартфон", "phone"}
_SHOE_WORDS = {"nike", "adidas", "кроссовки", "sneakers", "air force"}


@dataclass(frozen=True)
class ProductSearchProfile:
    original_text: str
    cleaned_text: str
    brand: str | None
    model: str | None
    sku: str | None
    barcode: str | None
    size: str | None
    color: str | None
    memory: str | None
    category: str | None
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class MatchThresholds:
    min_match_score: int = 65
    likely_threshold: int = 82
    exact_threshold: int = 95
    ai_rerank_enabled: bool = False


@dataclass(frozen=True)
class ProductMatchDecision:
    score: int
    status: MatchStatus
    confidence: str
    label: str
    explanation: dict[str, Any]


def normalize_product_text(
    text: str | None,
    *,
    category_hint: str | None = None,
    raw_json: dict[str, Any] | None = None,
) -> ProductSearchProfile:
    original = text or ""
    normalized = _normalize_text(original)
    normalized = _normalize_memory_bundles(normalized)
    sku = _extract_sku(normalized, raw_json)
    barcode = _extract_barcode(normalized, raw_json)
    memory = _extract_memory(normalized, raw_json)
    size = _extract_size(normalized, raw_json)
    color = _extract_color(normalized, raw_json)
    category = _extract_category(normalized, category_hint)
    cleaned_tokens = tuple(
        token
        for token in re.findall(r"[a-zа-я0-9.]+", normalized)
        if token not in _NOISE_WORDS
    )
    brand = next((token for token in cleaned_tokens if token in _BRANDS), None)
    model = _extract_model(cleaned_tokens, brand, memory, color, size)
    cleaned_text = " ".join(cleaned_tokens)
    return ProductSearchProfile(
        original_text=original,
        cleaned_text=cleaned_text,
        brand=brand,
        model=model,
        sku=sku,
        barcode=barcode,
        size=size,
        color=color,
        memory=memory,
        category=category,
        tokens=cleaned_tokens,
    )


def build_search_variants(profile: ProductSearchProfile) -> tuple[str, ...]:
    variants: list[str] = []
    brand_model = " ".join(part for part in (profile.brand, profile.model) if part)
    if brand_model:
        full = _join_non_empty(brand_model, profile.memory, profile.color)
        with_memory = _join_non_empty(brand_model, profile.memory)
        for value in (full, with_memory, brand_model, profile.model):
            if value and value not in variants:
                variants.append(value)
    if profile.sku and profile.sku not in variants:
        variants.append(profile.sku)
    if profile.barcode and profile.barcode not in variants:
        variants.append(profile.barcode)
    if not variants and profile.cleaned_text:
        variants.append(profile.cleaned_text)
    return tuple(variants)


def score_product_match(
    target: ProductSearchProfile,
    candidate: ProductSearchProfile,
    thresholds: MatchThresholds,
) -> ProductMatchDecision:
    hard_reject = _hard_reject_reason(target, candidate)
    if hard_reject is not None:
        return ProductMatchDecision(
            score=0,
            status="rejected",
            confidence="none",
            label="analog",
            explanation=_explanation(
                target,
                candidate,
                score=0,
                status="rejected",
                thresholds=thresholds,
                reject_reason=hard_reject,
            ),
        )

    score = _score_text(target, candidate)
    signals: list[str] = []
    if _is_model_variant_difference(target.model, candidate.model):
        signals.append("model_variant_difference")
        score = min(score, thresholds.exact_threshold - 1)
    if target.barcode and target.barcode == candidate.barcode:
        signals.append("barcode_match")
        score = max(score, thresholds.exact_threshold)
    if target.sku and target.sku == candidate.sku:
        signals.append("sku_match")
        score = max(score, thresholds.exact_threshold)

    if score < thresholds.min_match_score:
        status: MatchStatus = "rejected"
    elif score >= thresholds.exact_threshold:
        status = "exact"
    elif score >= thresholds.likely_threshold:
        status = "likely"
    else:
        status = "weak"

    return ProductMatchDecision(
        score=score,
        status=status,
        confidence=_confidence_for_status(status),
        label=_label_for_status(status),
        explanation=_explanation(
            target,
            candidate,
            score=score,
            status=status,
            thresholds=thresholds,
            signals=signals,
        ),
    )


def thresholds_from_metadata(metadata_json: dict[str, Any] | None) -> MatchThresholds:
    matching = (metadata_json or {}).get("matching") or {}
    return MatchThresholds(
        min_match_score=_bounded_int(matching.get("min_match_score"), 65, 0, 100),
        likely_threshold=_bounded_int(matching.get("likely_threshold"), 82, 0, 100),
        exact_threshold=_bounded_int(matching.get("exact_threshold"), 95, 0, 100),
        ai_rerank_enabled=bool(matching.get("ai_rerank_enabled", False)),
    )


def materialize_feed_matches(
    session: Session,
    feed_source: ProductFeedSource,
    feed_items: list[ProductFeedItem],
) -> None:
    if not feed_source.enabled or not feed_items:
        return
    store_sources = session.scalars(
        select(StoreSource)
        .join(Store)
        .options(selectinload(StoreSource.store))
        .where(
            StoreSource.source_code == feed_source.source_code,
            StoreSource.enabled.is_(True),
            Store.enabled.is_(True),
        )
    ).all()
    if not store_sources:
        return

    tracked_products = session.scalars(
        select(TrackedProduct).where(
            TrackedProduct.region_code == feed_source.region_code,
            TrackedProduct.product_name.is_not(None),
        )
    ).all()
    if not tracked_products:
        return

    for store_source in store_sources:
        thresholds = thresholds_from_metadata(store_source.metadata_json)
        for feed_item in feed_items:
            candidate = normalize_product_text(
                feed_item.title,
                category_hint=feed_item.category_id,
                raw_json=feed_item.raw_json,
            )
            for tracked_product in tracked_products:
                target = normalize_product_text(tracked_product.product_name)
                decision = score_product_match(target, candidate, thresholds)
                if decision.status == "rejected":
                    continue
                _upsert_offer(
                    session,
                    tracked_product=tracked_product,
                    store_source=store_source,
                    feed_source=feed_source,
                    feed_item=feed_item,
                    decision=decision,
                )
    session.flush()


def _upsert_offer(
    session: Session,
    *,
    tracked_product: TrackedProduct,
    store_source: StoreSource,
    feed_source: ProductFeedSource,
    feed_item: ProductFeedItem,
    decision: ProductMatchDecision,
) -> None:
    external_product_id = feed_item.external_product_id or _hash_key(
        feed_item.canonical_url
    )
    match_key = f"feed:{feed_source.source_code}:{_hash_key(external_product_id)}"
    match_group = session.scalar(
        select(ProductMatchGroup).where(
            ProductMatchGroup.tracked_product_id == tracked_product.id,
            ProductMatchGroup.match_key == match_key,
        )
    )
    if match_group is None:
        match_group = ProductMatchGroup(
            tracked_product=tracked_product,
            match_key=match_key,
            confidence=decision.confidence,
            label=decision.label,
        )
        session.add(match_group)
        session.flush()
    else:
        match_group.confidence = decision.confidence
        match_group.label = decision.label

    offer = session.scalar(
        select(ProductOffer).where(
            ProductOffer.match_group_id == match_group.id,
            ProductOffer.store_id == store_source.store_id,
            ProductOffer.external_product_id == external_product_id,
            ProductOffer.region_code == feed_source.region_code,
        )
    )
    if offer is None:
        offer = ProductOffer(
            match_group=match_group,
            store=store_source.store,
            source_code=feed_source.source_code,
            external_product_id=external_product_id,
            region_code=feed_source.region_code,
            product_url=feed_item.canonical_url,
            price=feed_item.price,
            currency=feed_item.currency,
            availability=feed_item.availability,
            match_confidence=decision.confidence,
            match_label=decision.label,
        )
        session.add(offer)
    offer.product_url = feed_item.canonical_url
    offer.title = feed_item.title
    offer.price = feed_item.price
    offer.currency = feed_item.currency
    offer.availability = feed_item.availability
    offer.match_confidence = decision.confidence
    offer.match_label = decision.label
    offer.raw_json = {
        "feed_item_raw": _safe_raw_json(feed_item.raw_json),
        "match_score": decision.score,
        "match_status": decision.status,
        "match_explanation": decision.explanation,
    }


def _normalize_text(value: str) -> str:
    text = html.unescape(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.replace("ё", "е").replace("×", "x")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\"'`]", " ", text)
    text = re.sub(r"[^a-zа-я0-9./:-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_memory_bundles(text: str) -> str:
    return re.sub(
        r"\b\d{1,2}\s*/\s*(\d{2,4})\s*(gb|гб|tb|тб)\b",
        lambda match: f"{match.group(1)}{_memory_unit(match.group(2))}",
        text,
    )


def _extract_sku(text: str, raw_json: dict[str, Any] | None) -> str | None:
    raw_sku = _raw_value(raw_json, "sku", "article", "vendor_code")
    if raw_sku:
        return _normalize_identifier(raw_sku)
    match = re.search(r"\b(?:sku|артикул)[:\s-]+([a-z0-9-]{3,64})\b", text)
    return _normalize_identifier(match.group(1)) if match else None


def _extract_barcode(text: str, raw_json: dict[str, Any] | None) -> str | None:
    raw_barcode = _raw_value(raw_json, "barcode", "ean", "gtin")
    if raw_barcode and re.fullmatch(r"\d{8,14}", str(raw_barcode).strip()):
        return str(raw_barcode).strip()
    match = re.search(r"\b(?:ean|gtin|barcode)?\s*(\d{8,14})\b", text)
    return match.group(1) if match else None


def _extract_memory(text: str, raw_json: dict[str, Any] | None) -> str | None:
    raw_memory = _raw_value(raw_json, "memory", "storage")
    if raw_memory:
        normalized = _normalize_text(str(raw_memory))
        match = re.search(r"\b(\d{2,4})\s*(gb|гб|tb|тб)\b", normalized)
        if match:
            return f"{match.group(1)}{_memory_unit(match.group(2))}"
    matches = re.findall(r"\b(\d{2,4})\s*(gb|гб|tb|тб)\b", text)
    if not matches:
        return None
    amount, unit = matches[-1]
    return f"{amount}{_memory_unit(unit)}"


def _extract_size(text: str, raw_json: dict[str, Any] | None) -> str | None:
    raw_size = _raw_value(raw_json, "size")
    if raw_size:
        return _normalize_size(str(raw_size))
    eu_match = re.search(r"\b(?:eu|eur|размер)\s*(\d{2}(?:\.\d)?)\b", text)
    if eu_match:
        return _normalize_size(eu_match.group(1))
    screen_match = re.search(r"\b(\d\.\d)\b", text)
    if screen_match:
        return _normalize_size(screen_match.group(1))
    return None


def _extract_color(text: str, raw_json: dict[str, Any] | None) -> str | None:
    raw_color = _raw_value(raw_json, "color", "colour")
    if raw_color:
        normalized = _normalize_text(str(raw_color))
        return _COLOR_ALIASES.get(normalized, normalized)
    if "blue titanium" in text:
        return "blue titanium"
    for token in re.findall(r"[a-zа-я]+", text):
        color = _COLOR_ALIASES.get(token, token)
        if color in _COLORS:
            return color
    return None


def _extract_category(text: str, category_hint: str | None) -> str | None:
    hint = _normalize_text(category_hint or "")
    if hint:
        if "phone" in hint or "смартфон" in hint:
            return "phone"
        if "shoe" in hint or "кроссов" in hint:
            return "shoes"
    if any(word in text for word in _ACCESSORY_WORDS):
        return "accessory"
    if any(word in text for word in _PHONE_WORDS):
        return "phone"
    if any(word in text for word in _SHOE_WORDS):
        return "shoes"
    return None


def _extract_model(
    tokens: tuple[str, ...],
    brand: str | None,
    memory: str | None,
    color: str | None,
    size: str | None,
) -> str | None:
    if not brand or brand not in tokens:
        return None
    start = tokens.index(brand) + 1
    model_tokens: list[str] = []
    stop_values = {value for value in (memory, color, size) if value}
    for token in tokens[start:]:
        if token in stop_values or token in _COLORS:
            break
        if token in _NOISE_WORDS:
            continue
        if re.fullmatch(r"\d{8,14}", token):
            continue
        model_tokens.append(token)
    if not model_tokens:
        return None
    return " ".join(model_tokens)


def _hard_reject_reason(
    target: ProductSearchProfile,
    candidate: ProductSearchProfile,
) -> str | None:
    if target.category != "accessory" and candidate.category == "accessory":
        return "accessory_instead_of_product"
    if target.barcode and candidate.barcode and target.barcode != candidate.barcode:
        return "barcode_mismatch"
    if target.sku and candidate.sku and target.sku != candidate.sku:
        return "sku_mismatch"
    if target.memory and candidate.memory and target.memory != candidate.memory:
        return "memory_mismatch"
    if target.size and candidate.size and target.size != candidate.size:
        return "size_mismatch"
    if target.brand and candidate.brand and target.brand != candidate.brand:
        return "brand_mismatch"
    if _has_conflicting_model_number(target.model, candidate.model):
        return "model_mismatch"
    return None


def _score_text(target: ProductSearchProfile, candidate: ProductSearchProfile) -> int:
    target_variants = build_search_variants(target)
    candidate_variants = build_search_variants(candidate)
    scores: list[float] = []
    for left in target_variants:
        for right in candidate_variants:
            scores.append(fuzz.WRatio(left, right))
            scores.append(fuzz.token_set_ratio(left, right))
    if not scores:
        return 0
    return int(round(max(scores)))


def _has_conflicting_model_number(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if _is_model_variant_difference(left, right):
        return False
    left_numbers = set(re.findall(r"\d+", left))
    right_numbers = set(re.findall(r"\d+", right))
    return bool(left_numbers and right_numbers and left_numbers != right_numbers)


def _is_model_variant_difference(left: str | None, right: str | None) -> bool:
    if not left or not right or left == right:
        return False
    left_tokens = left.split()
    right_tokens = right.split()
    min_len = min(len(left_tokens), len(right_tokens))
    return left_tokens[:min_len] == right_tokens[:min_len]


def _confidence_for_status(status: MatchStatus) -> str:
    return {
        "exact": "exact",
        "likely": "high",
        "weak": "low",
        "rejected": "none",
    }[status]


def _label_for_status(status: MatchStatus) -> str:
    return "analog" if status in {"weak", "rejected"} else "same_product"


def _explanation(
    target: ProductSearchProfile,
    candidate: ProductSearchProfile,
    *,
    score: int,
    status: MatchStatus,
    thresholds: MatchThresholds,
    reject_reason: str | None = None,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    explanation: dict[str, Any] = {
        "score": score,
        "status": status,
        "target": _profile_payload(target),
        "candidate": _profile_payload(candidate),
        "thresholds": {
            "min_match_score": thresholds.min_match_score,
            "likely_threshold": thresholds.likely_threshold,
            "exact_threshold": thresholds.exact_threshold,
        },
        "signals": signals or [],
        "ai_rerank": "not_available" if thresholds.ai_rerank_enabled else "disabled",
    }
    if reject_reason is not None:
        explanation["reject_reason"] = reject_reason
    return explanation


def _profile_payload(profile: ProductSearchProfile) -> dict[str, Any]:
    return {
        "brand": profile.brand,
        "model": profile.model,
        "sku": profile.sku,
        "barcode": profile.barcode,
        "size": profile.size,
        "color": profile.color,
        "memory": profile.memory,
        "category": profile.category,
        "search_variants": list(build_search_variants(profile)),
    }


def _raw_value(raw_json: dict[str, Any] | None, *keys: str) -> Any:
    if not raw_json:
        return None
    for key in keys:
        value = raw_json.get(key)
        if value not in (None, ""):
            return value
    return None


def _memory_unit(unit: str) -> str:
    return "tb" if unit in {"tb", "тб"} else "gb"


def _normalize_identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9-]+", "", str(value).lower())


def _normalize_size(value: str) -> str:
    return value.strip().lower().replace(",", ".")


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _join_non_empty(*parts: str | None) -> str:
    return " ".join(part for part in parts if part)


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _safe_raw_json(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return strip_secret_like_keys(value)
