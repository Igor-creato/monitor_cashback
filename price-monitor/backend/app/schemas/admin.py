from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminOverviewResponse(BaseModel):
    products_total: int
    active_subscriptions_total: int
    fetch_jobs_queued: int
    fetch_jobs_failed_24h: int
    cashback_no_partner_total: int
    cashback_estimated_total: int
    cashback_exact_total: int
    notification_events_pending: int
    sources_enabled: int


class AdminSourceResponse(BaseModel):
    source_code: str
    source_name: str
    enabled: bool
    fetch_strategy: str
    min_fetch_interval_minutes: int
    max_failures_before_quarantine: int
    browser_fallback_enabled: bool


class AdminSourcesResponse(BaseModel):
    items: list[AdminSourceResponse]


class AdminSourcePatch(BaseModel):
    enabled: bool | None = None
    min_fetch_interval_minutes: int | None = None
    max_failures_before_quarantine: int | None = None
    browser_fallback_enabled: bool | None = None

    model_config = ConfigDict(extra="ignore")


class AdminProductCashbackResponse(BaseModel):
    cashback_status: str
    merchant_id: str | None = None
    merchant_name: str | None = None
    network: str | None = None
    offer_id: str | None = None
    user_cashback_exact_rate: str | None = None
    user_cashback_min_rate: str | None = None
    user_cashback_max_rate: str | None = None
    expected_cashback_exact: str | None = None
    expected_cashback_min: str | None = None
    expected_cashback_max: str | None = None
    effective_price: str | None = None
    effective_price_conservative: str | None = None
    confidence: str | None = None
    display_policy: str | None = None
    message: str | None = None


class AdminProductResponse(BaseModel):
    tracked_product_id: int
    source: str
    external_product_id: str
    canonical_url: str
    region_code: str
    product_name: str | None
    image_url: str | None
    last_price: str | None
    last_old_price: str | None
    currency: str | None
    last_availability: bool
    last_checked_at: datetime | None
    last_success_at: datetime | None
    last_status: str | None
    fail_count: int
    cashback_status: str
    cashback: AdminProductCashbackResponse | None = None


class AdminProductsResponse(BaseModel):
    items: list[AdminProductResponse]


class AdminJobResponse(BaseModel):
    job_id: int
    tracked_product_id: int
    source: str
    status: str
    priority: int
    attempt: int
    reason: str | None
    next_run_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_text: str | None


class AdminJobsResponse(BaseModel):
    items: list[AdminJobResponse]


class AdminErrorResponse(BaseModel):
    error_type: str
    record_id: int
    source: str | None = None
    tracked_product_id: int | None = None
    status: str | None = None
    message: str | None = None
    created_at: datetime | None = None


class AdminErrorsResponse(BaseModel):
    items: list[AdminErrorResponse]
