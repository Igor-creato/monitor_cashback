from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.monitoring import SourceFetchProfile, Store, StoreSource


@dataclass(frozen=True)
class SourceProfile:
    source_code: str
    difficulty_class: str
    preferred_transport: str
    fallback_transports: list[str]
    proxy_tier_policy: str
    browser_required: bool
    extraction_mode: str
    image_policy: str
    enabled: bool


LIGHT_SOURCE_CODES = frozenset({"testshop", "wb", "wildberries"})
MEDIUM_SOURCE_CODES = frozenset({"example_market", "ali", "aliexpress", "amazon"})
HEAVY_SOURCE_CODES = frozenset({"demo_store"})
OZON_SOURCE_CODES = frozenset({"ozon"})


def get_source_profile(
    source_code: str,
    *,
    session: Session | None = None,
) -> SourceProfile:
    if session is not None:
        return _get_source_profile(source_code, session)

    if SessionLocal is None:
        return select_default_profile_for_source(source_code)

    with SessionLocal() as owned_session:
        return _get_source_profile(source_code, owned_session)


def select_default_profile_for_source(source_code: str) -> SourceProfile:
    if source_code in OZON_SOURCE_CODES:
        return SourceProfile(
            source_code=source_code,
            difficulty_class="light",
            preferred_transport="curl_cffi",
            fallback_transports=["direct_http"],
            proxy_tier_policy="cheap_first",
            browser_required=False,
            extraction_mode="ozon_public_page",
            image_policy="copy_to_object_storage",
            enabled=True,
        )

    if source_code in LIGHT_SOURCE_CODES:
        return SourceProfile(
            source_code=source_code,
            difficulty_class="light",
            preferred_transport="curl_cffi",
            fallback_transports=["direct_http"],
            proxy_tier_policy="cheap_first",
            browser_required=False,
            extraction_mode="json",
            image_policy="copy_to_object_storage",
            enabled=True,
        )

    if source_code in MEDIUM_SOURCE_CODES:
        return SourceProfile(
            source_code=source_code,
            difficulty_class="medium",
            preferred_transport="crawl4ai",
            fallback_transports=["playwright", "curl_cffi"],
            proxy_tier_policy="residential_first",
            browser_required=True,
            extraction_mode="css",
            image_policy="copy_to_object_storage",
            enabled=True,
        )

    if source_code in HEAVY_SOURCE_CODES:
        return SourceProfile(
            source_code=source_code,
            difficulty_class="heavy",
            preferred_transport="camoufox",
            fallback_transports=["playwright"],
            proxy_tier_policy="premium_only",
            browser_required=True,
            extraction_mode="hybrid",
            image_policy="copy_to_object_storage",
            enabled=True,
        )

    return SourceProfile(
        source_code=source_code,
        difficulty_class="light",
        preferred_transport="direct_http",
        fallback_transports=[],
        proxy_tier_policy="none",
        browser_required=False,
        extraction_mode="json",
        image_policy="copy_to_object_storage",
        enabled=False,
    )


def is_browser_required(
    source_code: str,
    *,
    session: Session | None = None,
) -> bool:
    return get_source_profile(source_code, session=session).browser_required


def _get_source_profile(source_code: str, session: Session) -> SourceProfile:
    stored_profile = session.scalar(
        select(SourceFetchProfile).where(SourceFetchProfile.source_code == source_code)
    )
    if stored_profile is None:
        store_source = _get_enabled_store_source(source_code, session)
        if store_source is not None:
            return _profile_from_store_source(store_source)
        return select_default_profile_for_source(source_code)
    return _serialize_profile(stored_profile)


def _get_enabled_store_source(
    source_code: str,
    session: Session,
) -> StoreSource | None:
    return session.scalar(
        select(StoreSource)
        .join(Store)
        .where(
            StoreSource.source_code == source_code,
            StoreSource.enabled.is_(True),
            Store.enabled.is_(True),
        )
        .limit(1)
    )


def _profile_from_store_source(source: StoreSource) -> SourceProfile:
    difficulty_class = _difficulty_for_store_source(source)
    preferred_transport = _preferred_transport_for_store_source(
        difficulty_class,
        source.proxy_tier_policy,
    )
    return SourceProfile(
        source_code=source.source_code,
        difficulty_class=difficulty_class,
        preferred_transport=preferred_transport,
        fallback_transports=_fallback_transports_for_store_source(
            difficulty_class,
            source.proxy_tier_policy,
        ),
        proxy_tier_policy=source.proxy_tier_policy,
        browser_required=difficulty_class in {"medium", "heavy"},
        extraction_mode=source.extraction_mode,
        image_policy="copy_to_object_storage",
        enabled=True,
    )


def _difficulty_for_store_source(source: StoreSource) -> str:
    if source.proxy_tier_policy == "premium_only" or source.extraction_mode == "hybrid":
        return "heavy"
    if (
        source.proxy_tier_policy == "residential_first"
        or source.extraction_mode == "css"
    ):
        return "medium"
    return "light"


def _preferred_transport_for_store_source(
    difficulty_class: str,
    proxy_tier_policy: str,
) -> str:
    if difficulty_class == "heavy":
        return "camoufox"
    if difficulty_class == "medium":
        return "crawl4ai"
    if proxy_tier_policy == "cheap_first":
        return "curl_cffi"
    return "direct_http"


def _fallback_transports_for_store_source(
    difficulty_class: str,
    proxy_tier_policy: str,
) -> list[str]:
    if difficulty_class == "heavy":
        return ["playwright"]
    if difficulty_class == "medium":
        return ["playwright", "curl_cffi"]
    if proxy_tier_policy == "cheap_first":
        return ["direct_http"]
    return []


def _serialize_profile(profile: SourceFetchProfile) -> SourceProfile:
    return SourceProfile(
        source_code=profile.source_code,
        difficulty_class=profile.difficulty_class,
        preferred_transport=profile.preferred_transport,
        fallback_transports=list(profile.fallback_transports),
        proxy_tier_policy=profile.proxy_tier_policy,
        browser_required=profile.browser_required,
        extraction_mode=profile.extraction_mode,
        image_policy=profile.image_policy,
        enabled=profile.enabled,
    )
