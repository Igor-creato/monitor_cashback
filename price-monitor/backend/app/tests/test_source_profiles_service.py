from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.monitoring import FetchJob, SourceFetchProfile, Store, StoreSource
from app.services.source_profiles import (
    get_source_profile,
    is_browser_required,
    select_default_profile_for_source,
)


@pytest.fixture
def db_session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    import app.services.source_profiles as source_profiles

    monkeypatch.setattr(source_profiles, "SessionLocal", session_factory)

    with Session(engine) as session:
        yield session


def _fetch_job_count(session: Session) -> int:
    return session.scalar(select(func.count(FetchJob.id))) or 0


def test_wb_and_testshop_sources_use_light_profile() -> None:
    for source_code in ("testshop", "wb", "wildberries"):
        profile = select_default_profile_for_source(source_code)

        assert profile.source_code == source_code
        assert profile.difficulty_class == "light"
        assert profile.preferred_transport == "curl_cffi"
        assert profile.fallback_transports == ["direct_http"]
        assert profile.proxy_tier_policy == "cheap_first"
        assert profile.browser_required is False
        assert profile.extraction_mode == "json"
        assert profile.image_policy == "copy_to_object_storage"
        assert profile.enabled is True


def test_ali_and_example_sources_use_medium_profile() -> None:
    for source_code in ("example_market", "ali", "aliexpress", "amazon"):
        profile = select_default_profile_for_source(source_code)

        assert profile.source_code == source_code
        assert profile.difficulty_class == "medium"
        assert profile.preferred_transport == "crawl4ai"
        assert profile.fallback_transports == ["playwright", "curl_cffi"]
        assert profile.proxy_tier_policy == "residential_first"
        assert profile.browser_required is True
        assert profile.extraction_mode == "css"
        assert profile.image_policy == "copy_to_object_storage"
        assert profile.enabled is True


def test_demo_source_uses_heavy_profile() -> None:
    for source_code in ("demo_store",):
        profile = select_default_profile_for_source(source_code)

        assert profile.source_code == source_code
        assert profile.difficulty_class == "heavy"
        assert profile.preferred_transport == "camoufox"
        assert profile.fallback_transports == ["playwright"]
        assert profile.proxy_tier_policy == "premium_only"
        assert profile.browser_required is True
        assert profile.extraction_mode == "hybrid"
        assert profile.image_policy == "copy_to_object_storage"
        assert profile.enabled is True


def test_ozon_uses_public_page_http_profile() -> None:
    profile = select_default_profile_for_source("ozon")

    assert profile.source_code == "ozon"
    assert profile.difficulty_class == "light"
    assert profile.preferred_transport == "curl_cffi"
    assert profile.fallback_transports == ["direct_http"]
    assert profile.proxy_tier_policy == "cheap_first"
    assert profile.browser_required is False
    assert profile.extraction_mode == "ozon_public_page"
    assert profile.image_policy == "copy_to_object_storage"
    assert profile.enabled is True


def test_unknown_source_returns_safe_disabled_default() -> None:
    profile = select_default_profile_for_source("unknown_source")

    assert profile.source_code == "unknown_source"
    assert profile.difficulty_class == "light"
    assert profile.preferred_transport == "direct_http"
    assert profile.fallback_transports == []
    assert profile.proxy_tier_policy == "none"
    assert profile.browser_required is False
    assert profile.extraction_mode == "json"
    assert profile.image_policy == "copy_to_object_storage"
    assert profile.enabled is False


def test_production_like_sources_copy_images_to_object_storage() -> None:
    for source_code in ("wb", "ali", "amazon", "ozon"):
        profile = select_default_profile_for_source(source_code)

        assert profile.image_policy == "copy_to_object_storage"


def test_get_source_profile_reads_persisted_override(db_session: Session) -> None:
    stored = SourceFetchProfile(
        source_code="testshop",
        difficulty_class="heavy",
        preferred_transport="playwright",
        fallback_transports=["curl_cffi"],
        proxy_tier_policy="residential_first",
        browser_required=True,
        extraction_mode="hybrid",
        image_policy="copy_to_object_storage",
        enabled=False,
    )
    db_session.add(stored)
    db_session.commit()

    profile = get_source_profile("testshop", session=db_session)

    assert profile.source_code == "testshop"
    assert profile.difficulty_class == "heavy"
    assert profile.preferred_transport == "playwright"
    assert profile.fallback_transports == ["curl_cffi"]
    assert profile.proxy_tier_policy == "residential_first"
    assert profile.browser_required is True
    assert profile.extraction_mode == "hybrid"
    assert profile.image_policy == "copy_to_object_storage"
    assert profile.enabled is False


def test_get_source_profile_uses_enabled_admin_store_source(
    db_session: Session,
) -> None:
    store = Store(
        store_code="dns_shop_ru",
        display_name="DNS",
        enabled=True,
    )
    db_session.add(store)
    db_session.flush()
    db_session.add(
        StoreSource(
            store=store,
            source_code="dns_shop_ru-default",
            display_name="DNS default",
            source_type="api",
            enabled=True,
            extraction_mode="json",
            proxy_tier_policy="none",
            domains_json=["dns-shop.ru", "www.dns-shop.ru"],
        )
    )
    db_session.commit()

    profile = get_source_profile("dns_shop_ru-default", session=db_session)

    assert profile.source_code == "dns_shop_ru-default"
    assert profile.difficulty_class == "light"
    assert profile.preferred_transport == "direct_http"
    assert profile.fallback_transports == []
    assert profile.proxy_tier_policy == "none"
    assert profile.browser_required is False
    assert profile.extraction_mode == "json"
    assert profile.image_policy == "copy_to_object_storage"
    assert profile.enabled is True


def test_is_browser_required_uses_selected_profile(db_session: Session) -> None:
    assert is_browser_required("testshop", session=db_session) is False
    assert is_browser_required("example_market", session=db_session) is True
    assert is_browser_required("demo_store", session=db_session) is True


def test_profile_selection_does_not_create_fetch_jobs(db_session: Session) -> None:
    before_count = _fetch_job_count(db_session)

    get_source_profile("testshop", session=db_session)
    get_source_profile("example_market", session=db_session)
    is_browser_required("demo_store", session=db_session)

    assert before_count == 0
    assert _fetch_job_count(db_session) == 0
