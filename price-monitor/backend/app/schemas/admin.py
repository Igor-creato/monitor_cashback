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


class AdminFetchEconomicsSourceCostResponse(BaseModel):
    source_code: str
    total_cost: str
    success_count: int
    attempt_count: int
    cost_per_successful_fetch: str


class AdminFetchEconomicsResponse(BaseModel):
    period: str
    cost_per_successful_fetch: str
    success_rate: str
    browser_fallback_rate: str
    http_403_count: int
    http_429_count: int
    captcha_count: int
    proxy_cost_by_tier: dict[str, str]
    proxy_usage_by_tier: dict[str, int]
    source_costs: list[AdminFetchEconomicsSourceCostResponse]


class AdminProxyPoolResponse(BaseModel):
    pool_id: int
    source: str
    purpose: str
    enabled: bool
    tier: str
    cost_per_request: str | None
    cost_per_gb: str | None
    max_cost_per_success: str | None
    country_code: str | None
    region_code: str | None
    sticky_session_supported: bool
    priority: int
    endpoint_count: int
    enabled_endpoint_count: int
    created_at: datetime
    updated_at: datetime


class AdminProxyPoolsResponse(BaseModel):
    items: list[AdminProxyPoolResponse]


class AdminProxyEndpointResponse(BaseModel):
    endpoint_id: int
    enabled: bool
    max_concurrency: int
    current_concurrency: int
    cooldown_until: datetime | None
    success_rate_1h: float | None
    success_rate_24h: float | None
    avg_response_ms: int | None
    ban_score: int
    last_403_at: datetime | None
    last_429_at: datetime | None
    last_captcha_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminProxyPoolDetailResponse(AdminProxyPoolResponse):
    endpoints: list[AdminProxyEndpointResponse]


class AdminSourceHealthResponse(BaseModel):
    source_code: str
    period: str
    success_count: int
    failure_count: int
    total_count: int
    success_rate: str
    http_403_count: int
    http_429_count: int
    captcha_count: int
    timeout_count: int
    parser_error_count: int
    price_not_found_count: int
    cashback_api_error_count: int


class AdminFetchAttemptResponse(BaseModel):
    attempt_id: int
    fetch_job_id: int | None
    tracked_product_id: int
    source_code: str
    strategy: str
    proxy_pool_id: int | None
    proxy_endpoint_id: int | None
    worker_name: str | None
    status: str
    error_type: str | None
    http_status: int | None
    response_ms: int | None
    cost_estimated: str | None
    bytes_downloaded: int | None
    product_data_found: bool
    price_found: bool
    image_found: bool
    created_at: datetime


class AdminFetchAttemptsResponse(BaseModel):
    items: list[AdminFetchAttemptResponse]


class AdminMarketplaceConnectionResponse(BaseModel):
    connection_id: int
    site_id: str
    external_user_id: str
    marketplace: str
    status: str
    key_version: str | None
    has_secret: bool
    consent_version: str
    consented_at: datetime
    expires_at: datetime | None
    last_validated_at: datetime | None
    last_synced_at: datetime | None
    next_retry_at: datetime | None
    reconnect_reason: str | None
    created_at: datetime
    updated_at: datetime


class AdminMarketplaceConnectionsResponse(BaseModel):
    items: list[AdminMarketplaceConnectionResponse]
